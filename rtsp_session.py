"""
RTSP Session Module for Doorbell Porter System.

This module handles RTSP communication with the doorbell camera:
- Session establishment and management
- Authentication and keepalive
- SDP parsing and backchannel setup
- Socket management
- Request/response handling

The module provides:
1. RTSPSession: Main class for RTSP session management
2. RTSPError: Custom exception for RTSP-related errors
"""

import os
import socket
import hashlib
import logging
import time
from typing import Optional, Dict, Tuple, Any
from urllib.parse import urlparse

# Configure logger
logger = logging.getLogger('doorbell')

class RTSPError(Exception):
    """Custom exception for RTSP-related errors."""
    pass

class RTSPSession:
    """
    Manages RTSP session with a Reolink doorbell camera.
    
    This class handles:
    - Session establishment and teardown
    - Authentication
    - Keepalive
    - Backchannel setup
    - Socket management
    """
    
    def __init__(self, url: str, username: str, password: str):
        """
        Initialize RTSP session.
        
        Args:
            url: RTSP URL for the camera
            username: Authentication username
            password: Authentication password
        """
        # Connection parameters
        self.url = url
        self.username = username
        self.password = password
        parsed = urlparse(url)
        self.hostname = parsed.hostname
        self.port = parsed.port or 554
        
        # Session state
        self.session_id = None
        self.seq = 0
        self.auth_type = None
        self.realm = None
        self.nonce = None
        self.is_connected = True
        
        # Backchannel configuration
        self.backchannel_client_port = 49154
        self.backchannel_server_port = None
        self.backchannel_socket = None
        self.backchannel_configured = False
        self.backchannel_payload_type = 0
        
        # Session keepalive
        self.keepalive_interval = 15  # seconds
        self.last_keepalive = 0

    def _create_auth_header(self, method: str, uri: str) -> str:
        """
        Create Digest authentication header.
        
        Args:
            method: RTSP method
            uri: Request URI
            
        Returns:
            Authentication header value
        """
        ha1 = hashlib.md5(f"{self.username}:{self.realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        response = hashlib.md5(f"{ha1}:{self.nonce}:{ha2}".encode()).hexdigest()
        
        return (f'Digest username="{self.username}", realm="{self.realm}", '
                f'nonce="{self.nonce}", uri="{uri}", response="{response}"')

    def send_request(self, method: str, headers: Optional[Dict[str, str]] = None, 
                    path: Optional[str] = None) -> Tuple[int, Dict[str, str], str]:
        """
        Send RTSP request and get response.
        
        Args:
            method: RTSP method
            headers: Optional additional headers
            path: Optional alternative request path
            
        Returns:
            Tuple containing:
            - Status code (int)
            - Response headers (dict)
            - Response body (str)
            
        Raises:
            RTSPError: For RTSP protocol errors
            socket.error: For connection issues
        """
        if headers is None:
            headers = {}
            
        self.seq += 1
        headers.update({
            'CSeq': str(self.seq),
            'User-Agent': 'Python RTSP Client',
            'Require': 'www.onvif.org/ver20/backchannel'
        })
        
        if self.session_id and method not in ['OPTIONS', 'DESCRIBE']:
            headers['Session'] = self.session_id
            
        target_uri = path if path else self.url
            
        if self.realm and self.nonce:
            headers['Authorization'] = self._create_auth_header(method, target_uri)
        
        request = f"{method} {target_uri} RTSP/1.0\r\n"
        for key, value in headers.items():
            request += f"{key}: {value}\r\n"
        request += "\r\n"
            
        if not hasattr(self, 'sock'):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.hostname, self.port))
        
        self.sock.send(request.encode())
        response = self.sock.recv(4096).decode()
        
        lines = response.split('\r\n')
        status_line = lines[0].split(' ')
        status = int(status_line[1])
        
        headers = {}
        body = ""
        header_done = False
        for line in lines[1:]:
            if not line:
                header_done = True
                continue
            if header_done:
                body += line + "\r\n"
            elif ': ' in line:
                key, value = line.split(': ', 1)
                headers[key] = value
                
        if status == 401 and not self.realm:
            auth_line = headers.get('WWW-Authenticate', '')
            if auth_line.startswith('Digest'):
                self.auth_type = 'Digest'
                for item in auth_line[7:].split(','):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        value = value.strip('"')
                        if key == 'realm':
                            self.realm = value
                        elif key == 'nonce':
                            self.nonce = value
                
                if self.realm and self.nonce:
                    return self.send_request(method, headers, path)
        
        return status, headers, body

    def parse_sdp(self, sdp: str) -> Optional[str]:
        """
        Parse SDP to find backchannel track.
        
        Args:
            sdp: Session Description Protocol content
            
        Returns:
            Backchannel track control URL or None if not found
        """
        lines = sdp.split('\n')
        current_media = None
        backchannel_track = None
        
        for line in lines:
            line = line.strip()
            
            if line.startswith('m=audio'):
                current_media = {}
                parts = line.split()
                if len(parts) > 3:
                    current_media['payload_type'] = parts[3]
                continue
                
            if current_media is not None:
                if line.startswith('a=control:'):
                    current_media['control'] = line.split(':', 1)[1]
                elif line.startswith('a=sendonly'):
                    current_media['direction'] = 'sendonly'
                elif line.startswith('a=rtpmap:'):
                    parts = line.split(':', 1)[1].split()
                    if len(parts) > 1 and ('PCMU' in parts[1] or 'PCMA' in parts[1]):
                        current_media['codec'] = parts[1]
                        logger.debug(f"Found audio codec: {parts[1]}")
                
                if all(k in current_media for k in ['control', 'direction', 'codec']) and \
                   current_media['direction'] == 'sendonly':
                    backchannel_track = current_media['control']
                    self.backchannel_payload_type = int(current_media['payload_type'])
                    logger.info(f"Found backchannel track: {backchannel_track} with payload type {self.backchannel_payload_type}")
                    break
        
        return backchannel_track

    def setup_backchannel(self) -> bool:
        """
        Setup RTSP session for backchannel audio.
        
        Returns:
            True if setup successful, False otherwise
            
        Raises:
            RTSPError: For RTSP protocol errors
            socket.error: For connection issues
        """
        try:
            logger.info("Setting up backchannel audio...")
            
            status, _, _ = self.send_request('OPTIONS', path=f"rtsp://{self.hostname}:{self.port}/")
            if status != 200:
                raise RTSPError(f"OPTIONS failed with status {status}")
            logger.debug("OPTIONS request successful")

            status, headers, sdp = self.send_request('DESCRIBE', {
                'Accept': 'application/sdp'
            })
            if status != 200:
                raise RTSPError(f"DESCRIBE failed with status {status}")
            logger.debug("DESCRIBE request successful")

            backchannel_track = self.parse_sdp(sdp)
            if not backchannel_track:
                logger.error("No backchannel track found in SDP")
                return False
            
            content_base = headers.get('Content-Base', self.url)
            if not content_base.endswith('/'):
                content_base += '/'

            setup_url = content_base + backchannel_track
            logger.info(f"Setting up backchannel at URL: {setup_url}")
            
            setup_headers = {
                'Transport': f'RTP/AVP;unicast;client_port={self.backchannel_client_port}-{self.backchannel_client_port+1}'
            }
            
            status, headers, _ = self.send_request('SETUP', setup_headers, path=setup_url)
            if status != 200:
                raise RTSPError(f"Backchannel SETUP failed with status {status}")
            
            transport = headers.get('Transport', '')
            if not transport:
                raise RTSPError("No transport header in SETUP response")
                
            if 'server_port=' not in transport:
                raise RTSPError("No server_port in transport header")
                
            try:
                server_ports = transport.split('server_port=')[1].split(';')[0]
                self.backchannel_server_port = int(server_ports.split('-')[0])
                logger.info(f"Backchannel server port: {self.backchannel_server_port}")
                
                if not (1024 <= self.backchannel_server_port <= 65535):
                    raise RTSPError(f"Invalid server port: {self.backchannel_server_port}")
            except (IndexError, ValueError) as e:
                raise RTSPError(f"Failed to parse server port: {e}")
            
            session = headers.get('Session', '')
            if not session:
                raise RTSPError("No session header in SETUP response")
                
            self.session_id = session.split(';')[0]
            logger.info(f"Established session ID: {self.session_id}")
            
            # Extract timeout if present
            if ';timeout=' in session:
                try:
                    timeout = int(session.split(';timeout=')[1])
                    logger.info(f"Server session timeout: {timeout} seconds")
                except (IndexError, ValueError):
                    logger.warning("Could not parse session timeout")

            # Send PLAY request
            status, _, _ = self.send_request('PLAY', {
                'Range': 'npt=0.000-'
            }, path=content_base)
            
            if status != 200:
                raise RTSPError(f"PLAY failed with status {status}")
            logger.debug("PLAY request successful")

            # Setup backchannel socket
            self.backchannel_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.backchannel_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            try:
                self.backchannel_socket.bind(('0.0.0.0', self.backchannel_client_port))
            except socket.error as e:
                logger.error(f"Failed to bind socket: {e}")
                return False
                
            self.backchannel_socket.settimeout(1.0)
            logger.info("Backchannel socket bound successfully")
            
            self.backchannel_configured = True
            logger.info("Backchannel configured successfully")

            return True

        except Exception as e:
            logger.error(f"Failed to setup backchannel: {str(e)}")
            return False

    def send_keepalive(self) -> bool:
        """
        Send keepalive request to maintain session.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if time.time() - self.last_keepalive > self.keepalive_interval:
                status, _, _ = self.send_request('GET_PARAMETER')
                if status == 200:
                    self.last_keepalive = time.time()
                    logger.debug("Keepalive sent successfully")
                    return True
                else:
                    logger.warning(f"Keepalive failed with status {status}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error in keepalive: {e}")
            return False

    def teardown(self):
        """Clean up RTSP session."""
        # Send TEARDOWN request
        if self.session_id:
            try:
                self.send_request('TEARDOWN', path=self.url)
            except Exception as e:
                logger.error(f"Error sending TEARDOWN request: {e}")

        # Close sockets
        if hasattr(self, 'sock'):
            try:
                self.sock.close()
                delattr(self, 'sock')
            except:
                pass
            
        if self.backchannel_socket:
            try:
                self.backchannel_socket.close()
                self.backchannel_socket = None
            except:
                pass
            
        # Reset session state
        self.session_id = None
        self.seq = 0
        self.auth_type = None
        self.realm = None
        self.nonce = None
        self.last_keepalive = 0
        self.backchannel_server_port = None
        self.backchannel_configured = False
        
        logger.info("RTSP session cleaned up")
