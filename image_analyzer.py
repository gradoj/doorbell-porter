"""
Image Analysis Module Using OpenAI's Vision Model.

This module provides functionality to analyze doorbell camera snapshots using
OpenAI's GPT-4 Vision model. It handles:
- Image encoding and validation
- API communication with OpenAI
- Custom analysis prompts
- Error handling and logging

The analyzer generates detailed descriptions of:
- People and their appearance
- Notable objects or activities
- Relevant contextual details
- Potential security concerns

Usage:
    analyzer = ImageAnalyzer(api_key)
    description = analyzer.analyze_snapshot('path/to/image.jpg')
"""

import base64
import logging
import os
from typing import Optional, Dict, Any, Union
from openai import OpenAI
from openai.types.chat import ChatCompletion
from .config import VISION_MODEL

#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

# Analysis Configuration
DEFAULT_MAX_TOKENS = 300
DEFAULT_PROMPT = (
    "Please describe who or what you see in this doorbell camera snapshot. "
    "Focus on any people, their appearance, and notable objects or activities. "
    "Be concise but detailed."
)

# Image Configuration
SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png']
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB limit for OpenAI

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

# Configure logger
logger = logging.getLogger('doorbell')

#------------------------------------------------------------------------------
# Image Analyzer Class
#------------------------------------------------------------------------------

class ImageAnalyzer:
    """
    Handles image analysis using OpenAI's vision model.
    
    This class manages:
    - Image validation and encoding
    - OpenAI API communication
    - Analysis prompt handling
    - Error management
    
    Attributes:
        client (OpenAI): OpenAI API client instance
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the image analyzer.
        
        Args:
            api_key: OpenAI API key for authentication
            
        Raises:
            ValueError: If API key is invalid or empty
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Invalid OpenAI API key")
        self.client = OpenAI(api_key=api_key)
        
    def _validate_image(self, image_path: str) -> None:
        """
        Validate image file before processing.
        
        Args:
            image_path: Path to the image file
            
        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If image format is unsupported or file is too large
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
            
        file_ext = os.path.splitext(image_path)[1].lower()
        if file_ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported image format: {file_ext}. "
                f"Supported formats: {', '.join(SUPPORTED_FORMATS)}"
            )
            
        file_size = os.path.getsize(image_path)
        if file_size > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image file too large: {file_size/1024/1024:.1f}MB. "
                f"Maximum size: {MAX_IMAGE_SIZE/1024/1024:.1f}MB"
            )
        
    def _encode_image(self, image_path: str) -> str:
        """
        Encode image to base64 string.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Base64 encoded image string
            
        Raises:
            IOError: If image file cannot be read
            Exception: For other encoding errors
        """
        try:
            self._validate_image(image_path)
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except IOError as e:
            logger.error(f"Error reading image file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error encoding image: {e}")
            raise
            
    def analyze_snapshot(self, image_path: str, prompt: Optional[str] = None) -> str:
        """
        Analyze snapshot using OpenAI's vision model.
        
        This method:
        1. Validates and encodes the image
        2. Sends analysis request to OpenAI
        3. Processes and returns the description
        
        Args:
            image_path: Path to the snapshot image
            prompt: Optional custom prompt for analysis
                   If not provided, uses default prompt
            
        Returns:
            Detailed description of the snapshot
            
        Raises:
            ValueError: For invalid inputs
            Exception: For API or processing errors
        """
        try:
            logger.info(f"Analyzing snapshot: {image_path}")
            
            # Encode image
            base64_image = self._encode_image(image_path)
            
            # Prepare analysis request
            messages = [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt or DEFAULT_PROMPT,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "auto"
                        },
                    },
                ],
            }]
            
            # Send analysis request
            response: ChatCompletion = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=messages,
                max_tokens=DEFAULT_MAX_TOKENS
            )
            
            # Extract and validate description
            if not response.choices:
                raise ValueError("No response received from OpenAI")
                
            description = response.choices[0].message.content
            if not description:
                raise ValueError("Empty description received from OpenAI")
                
            logger.info(f"Generated snapshot description: {description}")
            return description
            
        except Exception as e:
            error_msg = f"Error analyzing snapshot: {str(e)}"
            logger.error(error_msg)
            return error_msg
