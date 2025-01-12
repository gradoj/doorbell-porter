"""
Audio Handler Module for Doorbell Porter System.

This module manages audio processing and streaming:
- Audio queue management
- FFmpeg integration
- Audio processing pipelines
- Backchannel audio handling
- Audio format conversion

The audio processing pipeline includes:
- Sample rate conversion
- DC offset removal
- Volume control
- Noise gate
- Peak limiting
"""

import os
import subprocess
import audioop
import threading
import logging
import time
from queue import Queue, Full, Empty
from typing import Optional, Dict, List, Tuple, Any

from .rtsp_session import RTSPSession

# Configure logger
logger = logging.getLogger('doorbell')

class DoorbellAudioHandler:
    """
    Handles two-way audio communication with Reolink doorbell.
    
    This class manages audio processing and streaming, including:
    - Audio queue management
    - Real-time audio processing
    - Two-way communication
    - Quality control
    """
    
    def __init__(self, url: str, username: str, password: str):
        """Initialize the audio handler"""
        # Create RTSP session
        self.rtsp = RTSPSession(url, username, password)
        
        # Audio configuration
        self.CHANNELS = 1
        self.RATE = 8000  # G.711 rate
        self.CHUNK = 4096
        
        # Audio queues with optimized buffer sizes for lower latency
        self.incoming_queue = Queue(maxsize=50)  # From doorbell to OpenAI (~1s at 24kHz)
        self.outgoing_queue = Queue(maxsize=10)  # From OpenAI to doorbell (~200ms buffer)
        
        # Import config here to avoid circular imports
        from . import config
        self.config = config
        
        # Connection state
        self.is_recording = False
        self.is_connected = True
        self.use_ffmpeg_backchannel = config.USE_FFMPEG_BACKCHANNEL
        self.ffmpeg_backchannel_process = None
        
        # RTP state for backchannel
        self.backchannel_seq = 0
        self.backchannel_timestamp = 0
        self.backchannel_ssrc = os.urandom(4)

    def start_recording(self) -> None:
        """
        Start recording audio from doorbell.
        
        This method:
        1. Starts FFmpeg for audio capture
        2. Sets up backchannel if available
        3. Starts audio processing threads
        
        Raises:
            subprocess.SubprocessError: If FFmpeg fails to start
            Exception: For other initialization errors
        """
        self.is_recording = True
        
        # FFmpeg command for receiving audio with parameters from config
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', self.rtsp.url,
            '-acodec', 'pcm_s16le',
            '-ar', '24000',  # OpenAI's rate
            '-ac', str(self.CHANNELS),
            '-af', (f'volume={self.config.AUDIO_PROCESSING["INCOMING_AUDIO"]["VOLUME_SCALE"]},'
                   'highpass=f=100,lowpass=f=4000,'
                   'alimiter=limit=0.8'),  # Simple limiter to prevent clipping
            '-f', 'wav',
            'pipe:1'
        ]
        
        try:
            logger.info(f"Starting FFmpeg with command: {' '.join(ffmpeg_cmd)}")
            # Start FFmpeg process
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )
            logger.info("FFmpeg process started")
            
            # Start audio processing thread
            threading.Thread(target=self._process_audio, daemon=True).start()
            logger.info("Audio processing thread started")
            
            # Start backchannel if available
            if self.rtsp.setup_backchannel():
                # Start backchannel thread
                threading.Thread(target=self._handle_backchannel, daemon=True).start()
                # Start keepalive thread
                threading.Thread(target=self._keepalive_session, daemon=True).start()
                logger.info("Backchannel and keepalive threads started")
            else:
                logger.warning("Failed to setup backchannel")
            
        except Exception as e:
            logger.error(f"Error starting recording: {e}")
            self.cleanup()
            raise

    def _keepalive_session(self):
        """Send periodic keepalive requests to maintain RTSP session"""
        while self.is_connected:
            if not self.rtsp.send_keepalive():
                break
            time.sleep(1)

    def _process_audio(self) -> None:
        """
        Process audio from doorbell.
        
        This method continuously reads audio data from FFmpeg output,
        processes it, and puts it in the incoming queue for OpenAI.
        
        Raises:
            Exception: For audio processing errors
        """
        logger.info("Starting audio processing from doorbell")
        chunk_count = 0
        while self.is_recording and self.is_connected:
            try:
                audio_chunk = self.ffmpeg_process.stdout.read(self.CHUNK)
                if not audio_chunk:
                    logger.warning("No audio data received from FFmpeg")
                    stderr_output = self.ffmpeg_process.stderr.read()
                    if stderr_output:
                        logger.error(f"FFmpeg error output: {stderr_output.decode()}")
                    break
                
                try:
                    # Try to make room in queue if full
                    if self.incoming_queue.full():
                        try:
                            self.incoming_queue.get_nowait()  # Remove oldest chunk
                        except Empty:
                            pass
                    # Put new chunk with longer timeout and force flush if small
                    self.incoming_queue.put(audio_chunk, timeout=0.5)
                    if len(audio_chunk) < self.CHUNK:  # If chunk is smaller than buffer size
                        # Add silence to force flush
                        padding = b'\x00' * (self.CHUNK - len(audio_chunk))
                        self.incoming_queue.put(padding, timeout=0.5)
                except Full:
                    logger.warning("Incoming queue full, dropping audio chunk")
                    continue
                chunk_count += 1
                if chunk_count % 100 == 0:
                    logger.info(f"Processed {chunk_count} audio chunks")
                
            except Exception as e:
                if not self.is_connected:
                    break
                logger.error(f"Error processing doorbell audio: {e}")

    def interrupt_playback(self):
        """
        Simple interrupt of current audio playback.
        Clears audio queues to stop current playback immediately.
        """
        logger.info("Interrupting audio playback")
        
        # Clear incoming queue
        while not self.incoming_queue.empty():
            try:
                self.incoming_queue.get_nowait()
            except Empty:
                break
                
        # Clear outgoing queue
        while not self.outgoing_queue.empty():
            try:
                self.outgoing_queue.get_nowait()
            except Empty:
                break
                
        logger.info("Audio playback interrupted")

    def _handle_backchannel(self) -> None:
        """
        Handle sending audio back to doorbell.
        
        This method starts either FFmpeg or audioop-based
        backchannel processing based on configuration.
        """
        logger.info("Starting backchannel audio handler")
        
        if self.use_ffmpeg_backchannel:
            self._handle_ffmpeg_backchannel()
        else:
            self._handle_audioop_backchannel()

    def _handle_ffmpeg_backchannel(self) -> None:
        """Process backchannel audio using FFmpeg"""
        packet_count = 0
        
        while self.is_recording and self.is_connected:
            try:
                try:
                    # Non-blocking get with timeout
                    # Longer timeout to handle processing delays
                    audio_data = self.outgoing_queue.get(timeout=0.5)
                    
                    # Force immediate playback for small chunks
                    if len(audio_data) < self.CHUNK:
                        # Add silence padding to reach minimum chunk size
                        padding = b'\x00' * (self.CHUNK - len(audio_data))
                        audio_data += padding
                        logger.debug("Added padding to small audio chunk")
                except Empty:
                    continue
                    
                logger.debug(f"Processing outgoing audio chunk: {len(audio_data)} bytes")
                
                # FFmpeg command for processing chunk
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-f', 's16le',        # Input format
                    '-ar', '24000',       # Input rate
                    '-ac', '1',           # Input channels
                    '-i', 'pipe:0',       # Read from stdin
                    '-af', (f'volume={self.config.AUDIO_PROCESSING["BACKCHANNEL"]["VOLUME_TARGET_RATIO"]},'
                           'highpass=f=100,lowpass=f=4000,'
                           f'alimiter=limit={self.config.AUDIO_PROCESSING["BACKCHANNEL"]["PEAK_LIMITER_THRESHOLD"]/32767}'),
                    '-acodec', 'pcm_mulaw',  # μ-law encoding
                    '-ar', '8000',        # Output rate
                    '-ac', '1',           # Output channels
                    '-f', 'mulaw',        # Output format
                    'pipe:1'              # Write to stdout
                ]
                
                # Process chunk through FFmpeg
                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Write input data
                process.stdin.write(audio_data)
                process.stdin.close()
                
                # Read output data
                encoded_data = process.stdout.read()
                process.wait()
                
                if not encoded_data or len(encoded_data) != 160:  # One packet worth
                    continue
                
                # Create RTP header
                header = bytearray(12)
                header[0] = 0x80
                header[1] = self.rtsp.backchannel_payload_type
                
                header[2] = (self.backchannel_seq >> 8) & 0xFF
                header[3] = self.backchannel_seq & 0xFF
                self.backchannel_seq = (self.backchannel_seq + 1) & 0xFFFF
                
                header[4:8] = self.backchannel_timestamp.to_bytes(4, 'big')
                self.backchannel_timestamp = (self.backchannel_timestamp + 160) & 0xFFFFFFFF
                
                header[8:12] = self.backchannel_ssrc
                
                # Send RTP packet
                rtp_packet = bytes(header) + encoded_data
                if not self.rtsp.backchannel_socket:
                    logger.error("Backchannel socket not initialized")
                    break
                if not self.rtsp.backchannel_server_port:
                    logger.error("Backchannel server port not set")
                    break
                    
                try:
                    self.rtsp.backchannel_socket.sendto(rtp_packet, (self.rtsp.hostname, self.rtsp.backchannel_server_port))
                    if packet_count % 500 == 0:  # Log every 500 packets (~10 seconds)
                        logger.info(f"Backchannel active - sent {packet_count} packets")
                    time.sleep(0.02)  # 20ms delay between packets
                except Exception as e:
                    logger.error(f"Failed to send RTP packet: {e}")
                    self.rtsp.backchannel_socket = None  # Force reconnection
                    break
                packet_count += 1
                if packet_count % 1000 == 0:
                    logger.info(f"Sent {packet_count} RTP packets to doorbell")
                
            except Exception as e:
                # Only break on connection loss, not interrupts
                if not self.is_connected:
                    break
                # Log error but continue if it's just an interrupt
                logger.error(f"Error in FFmpeg backchannel: {e}")

    def _handle_audioop_backchannel(self):
        """Process backchannel audio using audioop with enhanced processing"""
        packet_count = 0
        
        while self.is_recording and self.is_connected:
            try:
                try:
                    # Non-blocking get with timeout
                    # Longer timeout to handle processing delays
                    audio_data = self.outgoing_queue.get(timeout=0.5)
                    
                    # Force immediate playback for small chunks
                    if len(audio_data) < self.CHUNK:
                        # Add silence padding to reach minimum chunk size
                        padding = b'\x00' * (self.CHUNK - len(audio_data))
                        audio_data += padding
                        logger.debug("Added padding to small audio chunk")
                except Empty:
                    continue
                    
                logger.debug(f"Processing outgoing audio chunk: {len(audio_data)} bytes")
                
                # Resampling based on config
                if not hasattr(self, 'resample_state'):
                    self.resample_state = None
                    
                if self.config.AUDIO_PROCESSING['BACKCHANNEL']['ENABLE_SMOOTH_RESAMPLING']:
                    # Two-step resampling for better quality
                    if not hasattr(self, 'resample_state_1'):
                        self.resample_state_1 = None
                    intermediate_data, self.resample_state_1 = audioop.ratecv(
                        audio_data, 2, 1, 24000, 16000, self.resample_state_1
                    )
                    resampled_data, self.resample_state = audioop.ratecv(
                        intermediate_data, 2, 1, 16000, 8000, self.resample_state
                    )
                else:
                    # Direct resampling
                    resampled_data, self.resample_state = audioop.ratecv(
                        audio_data, 2, 1, 24000, 8000, self.resample_state
                    )
                
                # Remove DC offset if enabled
                if self.config.AUDIO_PROCESSING['BACKCHANNEL']['DC_OFFSET_REMOVAL']:
                    resampled_data = audioop.bias(resampled_data, 2, 0)
                
                # Process in 160-byte chunks (one packet worth)
                while len(resampled_data) >= 320:  # Process all chunks
                    chunk = resampled_data[:320]
                    resampled_data = resampled_data[320:]
                    
                    # Simple volume adjustment
                    max_sample = audioop.max(chunk, 2)
                    if max_sample > 0:
                        scale = min(1.0, 32767 * self.config.AUDIO_PROCESSING['BACKCHANNEL']['VOLUME_TARGET_RATIO'] / max_sample)
                        chunk = audioop.mul(chunk, 2, scale)
                    
                    # Gentle noise gate with fade
                    rms = audioop.rms(chunk, 2)
                    if rms < self.config.AUDIO_PROCESSING['BACKCHANNEL']['NOISE_GATE_THRESHOLD']:
                        # Instead of silence, fade to very quiet
                        scale = max(0.01, rms / self.config.AUDIO_PROCESSING['BACKCHANNEL']['NOISE_GATE_THRESHOLD'])
                        chunk = audioop.mul(chunk, 2, scale)
                    
                    # Simple peak limiting to prevent clipping
                    max_sample = audioop.max(chunk, 2)
                    if max_sample > self.config.AUDIO_PROCESSING['BACKCHANNEL']['PEAK_LIMITER_THRESHOLD']:
                        scale = self.config.AUDIO_PROCESSING['BACKCHANNEL']['PEAK_LIMITER_THRESHOLD'] / max_sample
                        chunk = audioop.mul(chunk, 2, scale)
                    
                    # Convert to μ-law
                    encoded_data = audioop.lin2ulaw(chunk, 2)
                    if len(encoded_data) == 160:  # One packet worth
                        # Create RTP header
                        header = bytearray(12)
                        header[0] = 0x80
                        header[1] = self.rtsp.backchannel_payload_type
                        
                        header[2] = (self.backchannel_seq >> 8) & 0xFF
                        header[3] = self.backchannel_seq & 0xFF
                        self.backchannel_seq = (self.backchannel_seq + 1) & 0xFFFF
                        
                        header[4:8] = self.backchannel_timestamp.to_bytes(4, 'big')
                        self.backchannel_timestamp = (self.backchannel_timestamp + 160) & 0xFFFFFFFF
                        
                        header[8:12] = self.backchannel_ssrc
                        
                        # Send RTP packet
                        rtp_packet = bytes(header) + encoded_data
                        if self.rtsp.backchannel_socket and self.rtsp.backchannel_server_port:
                            try:
                                self.rtsp.backchannel_socket.sendto(rtp_packet, (self.rtsp.hostname, self.rtsp.backchannel_server_port))
                                if packet_count % 500 == 0:  # Log every 500 packets (~10 seconds)
                                    logger.info(f"Backchannel active - sent {packet_count} packets")
                                time.sleep(0.01)  # 10ms delay between packets
                            except Exception as e:
                                logger.error(f"Failed to send RTP packet: {e}")
                                # Attempt to recover from packet drop
                                try:
                                    if not self.rtsp.send_keepalive():
                                        logger.error("Failed to recover connection")
                                        self.rtsp.backchannel_socket = None  # Force reconnection
                                        break
                                    logger.info("Recovered from packet drop")
                                    continue
                                except Exception as recovery_error:
                                    logger.error(f"Recovery failed: {recovery_error}")
                                    self.rtsp.backchannel_socket = None  # Force reconnection
                                    break
                            packet_count += 1
                            
                        else:
                            logger.warning("Backchannel not properly configured")
                
                if packet_count % 1000 == 0:  # Log occasionally
                    logger.info(f"Sent {packet_count} RTP packets to doorbell")
                    
            except Exception as e:
                # Only break on connection loss, not interrupts
                if not self.is_connected:
                    break
                # Log error but continue if it's just an interrupt
                logger.error(f"Error in backchannel: {e}")

    def disconnect_audio(self) -> bool:
        """
        Safely disconnect the current two-way voice communication session.
        Waits for any remaining audio to finish playing before disconnecting.
        Keeps the program running to handle future connections.
        
        Returns:
            bool: True if disconnection was successful, False otherwise
        """
        try:
            logger.info("Waiting for audio playback to complete...")
            # Wait for outgoing queue to be empty (max 5 seconds)
            start_time = time.time()
            while not self.outgoing_queue.empty():
                if time.time() - start_time > 5:
                    logger.warning("Timeout waiting for audio playback")
                    break
                time.sleep(0.1)
            
            logger.info("Disconnecting two-way voice communication")
            self.cleanup_session()  # Use session cleanup instead of full cleanup
            return True
        except Exception as e:
            logger.error(f"Error disconnecting audio: {e}")
            return False
            
    def cleanup_session(self):
        """Clean up current audio session without ending connection"""
        # Stop recording
        self.is_recording = False
        
        # Terminate FFmpeg processes
        if hasattr(self, 'ffmpeg_process'):
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=5)
            except:
                try:
                    self.ffmpeg_process.kill()
                except:
                    pass
                
        if self.ffmpeg_backchannel_process:
            try:
                self.ffmpeg_backchannel_process.terminate()
                self.ffmpeg_backchannel_process.wait(timeout=5)
            except:
                try:
                    self.ffmpeg_backchannel_process.kill()
                except:
                    pass
                    
            self.ffmpeg_backchannel_process = None
            
        # Clean up RTSP session
        self.rtsp.teardown()
        
        logger.info("Audio session cleanup completed")

    def cleanup(self):
        """Full cleanup for program exit"""
        self.is_connected = False  # Only set this during full cleanup
        self.cleanup_session()
        logger.info("Full cleanup completed")
