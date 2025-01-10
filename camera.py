"""
Camera Module for Doorbell Camera Operations.

This module provides functionality for interacting with a Reolink doorbell camera,
primarily focused on capturing snapshots. It supports:

Methods:
- API-based snapshot capture
- FFmpeg-based snapshot capture
- Resolution control
- Error handling and logging

The module can capture snapshots using either:
1. Reolink's HTTP API (default, more reliable)
2. FFmpeg (alternative method, useful for some camera models)

Snapshots are saved with timestamps and optional resolution information.
All operations include comprehensive error handling and logging.
"""

import os
import time
import logging
import subprocess
import requests
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any
from urllib.parse import urlparse
from . import config

#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

# API Configuration
API_ENDPOINT = "/cgi-bin/api.cgi"
RANDOM_STRING_LENGTH = 16
RANDOM_STRING_CHARS = string.ascii_letters + string.digits

# FFmpeg Configuration
FFMPEG_TIMEOUT = 10  # seconds
FFMPEG_TRANSPORT = "tcp"

# Image Configuration
JPEG_MAGIC_BYTES = b'\xFF\xD8\xFF'
SNAPSHOTS_DIR = "snapshots"

# Time Configuration
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

# Configure logger
logger = logging.getLogger('camera')

#------------------------------------------------------------------------------
# Camera Class
#------------------------------------------------------------------------------

class Camera:
    """
    Handles doorbell camera operations and snapshot capture.
    
    This class manages:
    - Camera connection details
    - Snapshot capture methods
    - Image saving and validation
    - Error handling
    
    Attributes:
        ip (str): Camera IP address
        username (str): Authentication username
        password (str): Authentication password
        channel (int): Camera channel number
        use_ffmpeg (bool): Whether to use FFmpeg for snapshots
    """
    
    def __init__(self, rtsp_url: str, username: str, password: str, 
                 channel: int = 0, use_ffmpeg: bool = False):
        """
        Initialize camera handler.
        
        Args:
            rtsp_url: Camera's RTSP URL
            username: Authentication username
            password: Authentication password
            channel: Camera channel number (default: 0)
            use_ffmpeg: Whether to use FFmpeg for snapshots (default: False)
            
        Raises:
            ValueError: If required parameters are invalid
        """
        parsed_url = urlparse(rtsp_url)
        if not parsed_url.hostname:
            raise ValueError("Invalid RTSP URL")
            
        self.ip = parsed_url.hostname
        self.username = username
        self.password = password
        self.channel = channel
        self.use_ffmpeg = use_ffmpeg
        
        # Ensure snapshots directory exists
        os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
        
    def _generate_rs(self) -> str:
        """
        Generate a random string for API requests.
        
        Returns:
            Random string for request identification
        """
        return ''.join(random.choices(
            RANDOM_STRING_CHARS, 
            k=RANDOM_STRING_LENGTH
        ))
        
    def _generate_filename(self, resolution: Optional[Union[str, Tuple[int, int]]] = None) -> str:
        """
        Generate snapshot filename with timestamp.
        
        Args:
            resolution: Optional resolution specification
            
        Returns:
            Generated filename with path
        """
        timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        
        if resolution:
            if isinstance(resolution, tuple):
                res_str = f"{resolution[0]}x{resolution[1]}"
            else:
                res_str = resolution
            return f"{SNAPSHOTS_DIR}/snapshot_{timestamp}_{res_str}.jpg"
        
        return f"{SNAPSHOTS_DIR}/snapshot_{timestamp}.jpg"
        
    def _take_snapshot_api(self, resolution: Optional[Tuple[int, int]] = None) -> str:
        """
        Take snapshot using Reolink API method.
        
        Args:
            resolution: Optional tuple of (width, height)
            
        Returns:
            Path to saved snapshot or error message
            
        Raises:
            requests.RequestException: If API request fails
            ValueError: If received data is invalid
        """
        try:
            # Prepare API request
            params: Dict[str, Any] = {
                'cmd': 'Snap',
                'channel': self.channel,
                'rs': self._generate_rs(),
                'user': self.username,
                'password': self.password
            }
            
            if resolution:
                params['width'], params['height'] = resolution
                
            url = f"http://{self.ip}{API_ENDPOINT}"
            
            # Make API request
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            # Validate image data
            if not response.content.startswith(JPEG_MAGIC_BYTES):
                raise ValueError("Received data is not a valid JPEG image")
                
            # Generate and save file
            filename = self._generate_filename(resolution)
            with open(filename, 'wb') as f:
                f.write(response.content)
                
            logger.info(f"Saved snapshot to {filename}")
            return filename
            
        except Exception as e:
            error_msg = f"Error taking snapshot via API: {str(e)}"
            logger.error(error_msg)
            return error_msg
            
    def _take_snapshot_ffmpeg(self, resolution: Optional[str] = None) -> str:
        """
        Take snapshot using FFmpeg method.
        
        Args:
            resolution: Optional string in format 'WIDTHxHEIGHT'
            
        Returns:
            Path to saved snapshot or error message
            
        Raises:
            subprocess.SubprocessError: If FFmpeg command fails
            subprocess.TimeoutExpired: If command times out
        """
        try:
            filename = self._generate_filename(resolution)
            
            # Build FFmpeg command
            command = [
                'ffmpeg',
                '-rtsp_transport', FFMPEG_TRANSPORT,
                '-i', f"rtsp://{self.username}:{self.password}@{self.ip}/h264Preview_01_main",
                '-frames:v', '1'
            ]
            
            # Add scale filter if resolution specified
            if resolution:
                command.extend(['-vf', f'scale={resolution.replace("x", ":")}'])
                
            command.append(filename)
            
            # Execute FFmpeg
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=FFMPEG_TIMEOUT
            )
            
            if result.returncode == 0:
                logger.info(f"Saved snapshot to {filename}")
                return filename
            else:
                error = result.stderr.decode()
                error_msg = f"FFmpeg error: {error}"
                logger.error(error_msg)
                return error_msg
                
        except subprocess.TimeoutExpired:
            error_msg = "Error: Snapshot timed out"
            logger.error(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"Error taking snapshot via FFmpeg: {str(e)}"
            logger.error(error_msg)
            return error_msg
            
    def take_snapshot(self, resolution: Optional[Union[str, Tuple[int, int]]] = None) -> str:
        """
        Take snapshot using configured method.
        
        Args:
            resolution: Optional resolution specification
                      For FFmpeg: string 'WIDTHxHEIGHT'
                      For API: tuple (width, height)
                      If None, uses default resolution
        
        Returns:
            Path to saved snapshot or error message
            
        Raises:
            ValueError: If resolution format is invalid
            Exception: For other errors during snapshot capture
        """
        try:
            logger.info(f"Taking snapshot with resolution: {resolution}")
            
            if self.use_ffmpeg:
                # Ensure resolution is in string format for FFmpeg
                if isinstance(resolution, tuple):
                    resolution = f"{resolution[0]}x{resolution[1]}"
                return self._take_snapshot_ffmpeg(resolution)
            else:
                # Ensure resolution is in tuple format for API
                if isinstance(resolution, str):
                    width, height = map(int, resolution.split('x'))
                    resolution = (width, height)
                elif resolution is None:
                    resolution = config.SNAPSHOT_RESOLUTION
                return self._take_snapshot_api(resolution)
                
        except Exception as e:
            error_msg = f"Error in take_snapshot: {str(e)}"
            logger.error(error_msg)
            return error_msg

#------------------------------------------------------------------------------
# Module-level interface
#------------------------------------------------------------------------------

# Create default camera instance
_default_camera = Camera(
    rtsp_url=config.DOORBELL_URL,
    username=config.DOORBELL_USERNAME,
    password=config.DOORBELL_PASSWORD,
    channel=config.SNAPSHOT_CHANNEL,
    use_ffmpeg=config.USE_FFMPEG_SNAPSHOT
)

def take_snapshot(resolution: Optional[Union[str, Tuple[int, int]]] = None) -> str:
    """
    Take snapshot using default camera instance.
    
    This is a convenience function that uses the default camera
    configuration from the config module.
    
    Args:
        resolution: Optional resolution specification
                  For FFmpeg: string 'WIDTHxHEIGHT'
                  For API: tuple (width, height)
                  If None, uses default resolution
    
    Returns:
        Path to saved snapshot or error message
    """
    return _default_camera.take_snapshot(resolution)
