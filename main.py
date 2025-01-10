"""
Main application module for the Doorbell Porter system.

This module serves as the entry point for the application and orchestrates all components
including the doorbell interface, OpenAI integration, and weather services. It handles:
- Real-time audio streaming with OpenAI
- Doorbell event processing
- Tool management for weather and doorbell functions
- WebSocket communication
- Error handling and logging

The application uses asyncio for concurrent operations and websockets for real-time
communication with OpenAI's API.
"""

import json
import base64
import asyncio
import websockets
import logging
import os
import sys
from typing import Optional, Callable, Awaitable

# Add parent directory to Python path for direct script execution
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from doorbell_porter_weather.config import (
    OPENAI_API_KEY,
    MODEL,
    VOICE,
    SYSTEM_MESSAGE,
    LOGGING_CONFIG
)
from doorbell_porter_weather.audio_handler import DoorbellAudioHandler
from doorbell_porter_weather.doorbell_handler import DoorbellEventHandler
from doorbell_porter_weather.tools import ToolManager

#------------------------------------------------------------------------------
# Logging Configuration
#------------------------------------------------------------------------------

# Configure logging
logging.basicConfig(
    format=LOGGING_CONFIG['format'],
    datefmt=LOGGING_CONFIG['datefmt'],
    level=LOGGING_CONFIG['level']
)

# Set up loggers
logger = logging.getLogger('app')
openai_logger = logging.getLogger('openai')
doorbell_logger = logging.getLogger('doorbell')
tool_logger = logging.getLogger('tool')

# Set specific logging levels from config
for logger_name, config in LOGGING_CONFIG['loggers'].items():
    logging.getLogger(logger_name).setLevel(config['level'])

#------------------------------------------------------------------------------
# Main Application Class
#------------------------------------------------------------------------------

class DoorbellPorterApp:
    """
    Main application class for the Doorbell Porter system.
    
    This class manages the core functionality of the doorbell porter system,
    including audio streaming, event handling, and OpenAI communication.
    
    Attributes:
        doorbell_handler (DoorbellEventHandler): Handles doorbell events and audio
        tool_manager (ToolManager): Manages available tools for OpenAI
        websocket (Optional[websockets.WebSocketClientProtocol]): WebSocket connection to OpenAI
        waiting_for_response (bool): Indicates if waiting for an OpenAI response
        send_task (Optional[asyncio.Task]): Task for sending audio to OpenAI
        receive_task (Optional[asyncio.Task]): Task for receiving responses from OpenAI
        is_disconnecting (bool): Indicates if the app is in the process of disconnecting
    """
    
    def __init__(self):
        """
        Initialize the application components.
        
        Raises:
            ValueError: If OPENAI_API_KEY is not set in environment variables
        """
        if not OPENAI_API_KEY:
            raise ValueError("Missing OPENAI_API_KEY in .env file")
            
        self.doorbell_handler = DoorbellEventHandler()
        self.tool_manager = ToolManager(doorbell_handler=self.doorbell_handler)
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.waiting_for_response = False
        self.send_task: Optional[asyncio.Task] = None
        self.receive_task: Optional[asyncio.Task] = None
        self.is_disconnecting = False
        self.current_response = ''
        
    async def handle_doorbell_event(self, prompt: str) -> None:
        """
        Handle doorbell events by sending them to OpenAI.
        
        Args:
            prompt (str): Event prompt to send to OpenAI
            
        Raises:
            Exception: If there's an error sending the event to OpenAI
        """
        if not self.websocket:
            logger.error("WebSocket not connected")
            return
            
        try:
            # Send event message
            await self.websocket.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": prompt
                    }]
                }
            }))
            
            # Request response
            self.waiting_for_response = True
            await self.websocket.send(json.dumps({
                "type": "response.create"
            }))
            
        except Exception as e:
            logger.error(f"Error handling doorbell event: {e}")

    async def send_audio(self) -> None:
        """
        Send audio data to OpenAI in real-time.
        
        This method continuously reads from the doorbell's incoming audio queue
        and sends the data to OpenAI via WebSocket. It accumulates audio data
        into buffers before sending to optimize network usage.
        
        Raises:
            websockets.exceptions.ConnectionClosed: If WebSocket connection is lost
            Exception: For other errors during audio transmission
        """
        message_count = 0
        audio_buffer = []
        last_audio_time = asyncio.get_event_loop().time()
        
        while self.doorbell_handler.doorbell.is_connected:
            current_time = asyncio.get_event_loop().time()
            
            # Handle audio
            if not self.doorbell_handler.doorbell.incoming_queue.empty():
                try:
                    audio_data = self.doorbell_handler.doorbell.incoming_queue.get()
                    audio_buffer.append(audio_data)
                    last_audio_time = current_time
                    
                    # Send accumulated audio after collecting enough or if enough time has passed
                    if len(audio_buffer) >= 5 or (current_time - last_audio_time) >= 0.5:
                        combined_audio = b''.join(audio_buffer)
                        audio_b64 = base64.b64encode(combined_audio).decode('utf-8')
                        await self.websocket.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": audio_b64
                        }))
                        message_count += 1
                        if message_count % 100 == 0:
                            logger.info(f"Sent {message_count} audio messages to OpenAI")
                        
                        # Clear buffer
                        audio_buffer = []
                        
                        # Only request a response if we have enough audio and no active response
                        if len(combined_audio) > 8192 and not self.waiting_for_response and not self.current_response:
                            self.waiting_for_response = True
                            await self.websocket.send(json.dumps({
                                "type": "response.create"
                            }))
                        
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    if not self.doorbell_handler.doorbell.is_connected:
                        break
                    logger.error(f"Error sending audio to OpenAI: {e}")
            await asyncio.sleep(0.01)

    async def receive_audio(self) -> None:
        """
        Handle incoming audio and messages from OpenAI.
        
        This method processes various types of responses from OpenAI including:
        - Audio responses (speech)
        - Transcripts of AI responses
        - Tool function calls
        - Error messages
        
        Raises:
            websockets.exceptions.ConnectionClosed: If WebSocket connection is lost
            Exception: For other errors during message processing
        """
        message_count = 0
        try:
            async for message in self.websocket:
                if not self.doorbell_handler.doorbell.is_connected:
                    break
                try:
                    response = json.loads(message)
                    msg_type = response.get('type', '')
                    
                    if msg_type == 'response.create':
                        # Reset transcript at start of new response
                        self.current_response = ''
                        self.waiting_for_response = True
                        
                    elif msg_type == 'response.start':
                        # Response is starting, make sure transcript is reset
                        self.current_response = ''
                        self.waiting_for_response = False
                        
                    elif msg_type == 'response.audio.delta':
                        message_count += 1
                        audio_data = base64.b64decode(response['delta'])
                        if message_count % 100 == 0:
                            logger.info(f"Processed {message_count} audio messages from OpenAI")
                        self.doorbell_handler.doorbell.outgoing_queue.put(audio_data)
                        
                    elif msg_type == 'response.audio_transcript.delta':
                        transcript = response.get('delta', '')
                        if transcript and transcript.strip():
                            logger.info(f"AI Transcript: {transcript.strip()}")
                            
                    elif msg_type == 'input_audio_buffer.speech_started':
                        logger.info('Speech detected, clearing audio buffers')
                        self.doorbell_handler.doorbell.interrupt_playback()
                    
                    elif msg_type == 'response.function_call_arguments.done':
                        tool_name = response.get('name', 'unknown')
                        logger.info(f"Tool Call: {tool_name}")
                        await self.tool_manager.handle_tool_call(self.websocket, response)
                    
                    elif msg_type == 'response.function_call_output':
                        logger.info(f"Tool Output: {response.get('output', '')}")
                        
                    elif msg_type == 'error':
                        error_details = response.get('error', {})
                        if error_details.get('code') == 'rate_limit_exceeded':
                            wait_time = error_details.get('message', '').split('Please try again in ')[1].split('.')[0]
                            logger.error(f"Rate limit exceeded. Please wait {wait_time} before trying again.")
                            self.doorbell_handler.cleanup()
                            return
                        else:
                            logger.error(f"Error from OpenAI: {response}")
                            # Reset state on error
                            self.waiting_for_response = False
                            self.current_response = ''
                    
                    elif msg_type == 'response.end':
                        # Reset state at end of response
                        self.waiting_for_response = False
                        self.current_response = ''
                        
                except Exception as e:
                    if not self.doorbell_handler.doorbell.is_connected:
                        break
                    logger.error(f"Error processing message: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            if not self.doorbell_handler.doorbell.is_connected:
                return
            logger.error(f"Error in receive_audio: {e}")

    async def run(self) -> None:
        """
        Run the main application.
        
        This method:
        1. Initializes the doorbell handler
        2. Starts the webhook server
        3. Establishes WebSocket connection with OpenAI
        4. Sets up the session configuration
        5. Starts audio streaming
        6. Manages concurrent tasks for sending and receiving data
        
        Raises:
            Exception: For any errors during application execution
        """
        try:
            # Initialize doorbell
            self.doorbell_handler.initialize_doorbell()
            self.doorbell_handler.set_event_callback(self.handle_doorbell_event)
            
            # Start webhook server
            logger.info("Starting webhook server...")
            await self.doorbell_handler.start_webhook_server()
            
            # Connect to OpenAI
            logger.info("Connecting to OpenAI...")
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
            
            try:
                ws = await websockets.connect(
                    f'wss://api.openai.com/v1/realtime?model={MODEL}',
                    additional_headers=headers
                )
            except TypeError:
                ws = await websockets.connect(
                    f'wss://api.openai.com/v1/realtime?model={MODEL}',
                    extra_headers=headers
                )

            async with ws as websocket:
                self.websocket = websocket
                
                # Initialize session
                logger.info("Initializing OpenAI session...")
                await websocket.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "turn_detection": {"type": "server_vad"},
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "voice": VOICE,
                        "instructions": SYSTEM_MESSAGE,
                        "modalities": ["text", "audio"],
                        "temperature": 0.8,
                        "tool_choice": "auto",
                        "tools": self.tool_manager.tool_definitions
                    }
                }))

                # Wait a moment for session to initialize
                await asyncio.sleep(1)
                logger.info("Session initialized")
                
                logger.info("Starting doorbell audio...")
                self.doorbell_handler.doorbell.start_recording()

                # Create tasks for sending and receiving audio
                self.send_task = asyncio.create_task(self.send_audio())
                self.receive_task = asyncio.create_task(self.receive_audio())

                try:
                    # Wait for both tasks to complete
                    await asyncio.gather(self.send_task, self.receive_task)
                except KeyboardInterrupt:
                    logger.info("Stopping...")
                except Exception as e:
                    if "keepalive ping timeout" in str(e):
                        logger.info("Connection timed out")
                    else:
                        logger.error(f"Error: {e}")
                finally:
                    # Cancel tasks and cleanup
                    if self.send_task:
                        self.send_task.cancel()
                    if self.receive_task:
                        self.receive_task.cancel()
                    await asyncio.sleep(0.5)
                    self.doorbell_handler.cleanup()

        except Exception as e:
            logger.error(f"Error: {e}")
            if self.doorbell_handler:
                self.doorbell_handler.cleanup()

#------------------------------------------------------------------------------
# Entry Point
#------------------------------------------------------------------------------

def main():
    """
    Entry point for the application.
    
    Initializes and runs the DoorbellPorterApp, handling keyboard interrupts
    for graceful shutdown.
    """
    try:
        app = DoorbellPorterApp()
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Exiting...")

if __name__ == "__main__":
    main()
