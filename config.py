"""Configuration Module for Doorbell Porter System.

This module centralizes all configuration settings and environment variables:
- Environment and API configurations
- Audio/video processing parameters
- Location and system settings
- Logging configuration

The module provides:
1. Environment Management: Loading and validation of environment variables
2. System Configuration: Core system and API settings
3. Audio Configuration: Processing parameters and quality settings
4. Camera Configuration: Resolution and connection settings
5. Location Settings: Default geographical coordinates
6. Logging Configuration: Log levels and formatting rules

All sensitive data (API keys, credentials) must be stored in .env file.
"""

#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import os
from typing import Dict, Tuple, Optional, Any
from dotenv import load_dotenv

#------------------------------------------------------------------------------
# Environment Configuration
#------------------------------------------------------------------------------

# Load environment variables
load_dotenv()

def get_required_env(key: str) -> str:
    """Get required environment variable or raise error if not found."""
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value

#------------------------------------------------------------------------------
# API Configuration
#------------------------------------------------------------------------------

# OpenAI API Configuration
# - API keys must be set in .env file
# - Model versions should be updated as new ones are released
OPENAI_API_KEY = get_required_env('OPENAI_API_KEY')
VOICE: str = 'alloy'  # Available voices: alloy, echo, fable, onyx, nova, shimmer

# Model Configuration
# - MODEL: Used for real-time audio conversations
# - VISION_MODEL: Used for image analysis
MODEL = 'gpt-4o-realtime-preview-2024-12-17'  # Real-time conversation model
VISION_MODEL = 'gpt-4o-mini'  # Vision analysis model

#------------------------------------------------------------------------------
# Feature Configuration
#------------------------------------------------------------------------------

# Enable/disable optional features
# Set to True to enable a feature, False to disable
FEATURES = {
    'WEATHER': True,        # OpenWeatherMap API for real-time weather data
                           # Requires OPENWEATHER_API_KEY in .env
                           # Provides temperature, conditions, humidity, wind
                           # Extended info: pressure, visibility, cloud cover
                           
    'LIGHT_CONTROL': True,  # Magic Home LED control via flux_led library
                           # Requires LED_IP in .env (e.g. 10.0.0.148)
                           # Supports: on/off control
                           # Auto-on in low light conditions
                           # Auto-off after inactivity
                           
    'VISION': True,         # Reolink camera vision features
                           # Uses doorbell's built-in camera
                           # Captures snapshots on events
                           # Analyzes images using OpenAI Vision
                           # Resolution: 640x480 (configurable)
}

#------------------------------------------------------------------------------
# Optional Feature Configuration
#------------------------------------------------------------------------------

# Optional environment variables based on enabled features
def _get_optional_env(key: str, required_feature: str) -> Optional[str]:
    """Get environment variable if its feature is enabled, otherwise return None."""
    if FEATURES[required_feature]:
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"Missing required environment variable for {required_feature}: {key}")
        return value
    return None

# Get optional API keys and configuration based on enabled features
WEATHER_API_KEY = _get_optional_env('OPENWEATHER_API_KEY', 'WEATHER')
LED_IP = _get_optional_env('LED_IP', 'LIGHT_CONTROL')

#------------------------------------------------------------------------------
# Doorbell Configuration
#------------------------------------------------------------------------------

# Required doorbell settings
DOORBELL_URL = get_required_env('DOORBELL_URL')
DOORBELL_USERNAME = get_required_env('DOORBELL_USERNAME')
DOORBELL_PASSWORD = get_required_env('DOORBELL_PASSWORD')
WEBHOOK_HOST = get_required_env('WEBHOOK_HOST')
WEBHOOK_PORT = int(get_required_env('WEBHOOK_PORT'))

#------------------------------------------------------------------------------
# Audio Configuration
#------------------------------------------------------------------------------

# Audio processing settings
CHUNK: int = 1024    # Buffer size in bytes (1024 to 8192)
                     # Smaller values reduce latency but increase CPU usage

CHANNELS: int = 1    # Number of audio channels
                     # 1: Mono (required for G.711)
                     # 2: Stereo (not supported)

RATE: int = 24000    # Sample rate in Hz
                     # 24000: OpenAI's preferred rate
                     # 8000: G.711 μ-law (for doorbell)

USE_FFMPEG_BACKCHANNEL: bool = False  # Audio processing method
                                     # True: Use FFmpeg (better quality, more CPU)
                                     # False: Use audioop (lower CPU, basic processing)

# Audio processing configuration
AUDIO_PROCESSING = {
    'INCOMING_AUDIO': {
        # Volume scaling factor for incoming audio (0.1 to 1.0)
        # Higher values increase volume, lower values decrease it
        'VOLUME_SCALE': '0.8',  # Moderate volume level
    },
    'BACKCHANNEL': {
        # Enable two-step resampling for better quality (24kHz -> 16kHz -> 8kHz)
        # True: Better quality but more CPU usage
        # False: Direct 24kHz -> 8kHz conversion
        'ENABLE_SMOOTH_RESAMPLING': True,  # Disabled for lower latency
        
        # Remove DC offset from audio signal
        # True: Prevents audio drift and improves quality
        # False: Raw audio without DC correction
        'DC_OFFSET_REMOVAL': False,
        
        # Minimum audio level to pass through (0 to 32767)
        # Higher values reduce background noise
        'NOISE_GATE_THRESHOLD': 1000,  # Lower threshold for smoother transitions
        
        # Volume adjustment ratio (0.0 to 1.0)
        # Controls overall volume level
        'VOLUME_TARGET_RATIO': 0.1,  # Increased for better audibility
        
        # Maximum allowed signal level (0 to 32767)
        # Prevents audio clipping
        'PEAK_LIMITER_THRESHOLD': 2000  # High threshold to preserve dynamics
    }
}

#------------------------------------------------------------------------------
# Camera Configuration
#------------------------------------------------------------------------------

# Camera settings
USE_FFMPEG_SNAPSHOT: bool = False      # Set to False to use direct API method
SNAPSHOT_RESOLUTION: Tuple[int, int] = (640, 480)  # Width x Height
SNAPSHOT_CHANNEL: int = 0              # Camera channel (usually 0)

#------------------------------------------------------------------------------
# Location Configuration
#------------------------------------------------------------------------------

# Default location (Denver, CO)
DEFAULT_LOCATION: Dict[str, Any] = {
    "name": "Denver",
    "lat": 39.7392,
    "lon": -104.9903
}

#------------------------------------------------------------------------------
# AI System Configuration
#------------------------------------------------------------------------------

# System message for the AI
SYSTEM_MESSAGE: str = """You are a helpful AI assistant speaking through a doorbell intercom system.
Keep your responses concise and clear, as if you're speaking through an intercom.
Be friendly but professional, and always remember you're acting as a doorbell porter/assistant.

You have access to these tools based on enabled features:

1. Voice Communication Tools (Always Available):
   - The connect_voice tool establishes two-way voice communication
   - The disconnect_voice tool ends the voice session
   - IMPORTANT: For voice communication:
     1. When someone is speaking:
        - Simply pause your response and wait
        - Do NOT call disconnect_voice
        - Speech detection is handled automatically
     2. For ending conversations:
        - Only call disconnect_voice when user explicitly says "goodbye", "hang up", or "disconnect"
        - First compose your complete goodbye message
        - Speak your entire goodbye message
        - Then wait 1-2 seconds
        - Only THEN call disconnect_voice
     3. NEVER call disconnect_voice:
        - When detecting normal speech during conversation
        - While you are still speaking
        - Before your goodbye message is complete
        - If you have more to say
        - Without saying a proper goodbye first

2. Optional Tools (Based on Configuration):
   
   Weather Information (if enabled):
   - Use the get_weather tool with latitude/longitude coordinates
   - Provides current conditions, temperature, humidity, and wind
   - Extended info includes pressure, visibility, cloud cover, sunrise/sunset times
   
   Camera Features (if enabled):
   - The take_snapshot tool captures images from the camera
   - Each snapshot is analyzed using vision AI
   - You receive both the snapshot path and a detailed analysis
   - You can request additional analysis using analyze_snapshot
   
   Light Control (if enabled):
   - Use turn_light_on to turn the light on
   - Use turn_light_off to turn the light off
   - Consider lighting conditions when managing the light
   - Remember to turn off the light when no longer needed

For conversations:
1. Call connect_voice to establish communication
2. Greet them warmly and professionally
3. Let them speak first after your greeting
4. Respond naturally to their questions or requests
5. If they ask about weather, provide that information
6. Keep responses focused and natural, avoiding repetitive phrases

For your initial greeting when the system starts:
1. Simply say "Hello! Welcome." and wait for visitors
2. Do not take snapshots or perform other actions until someone presses the doorbell or requests it"""

#------------------------------------------------------------------------------
# Logging Configuration
#------------------------------------------------------------------------------

# Configure logging settings
LOGGING_CONFIG: Dict[str, Any] = {
    'format': '%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s',
    'datefmt': '%Y-%m-%d %H:%M:%S',
    'level': 'INFO',
    'loggers': {
        'app': {'level': 'INFO'},
        'openai': {'level': 'WARNING'},
        'doorbell': {'level': 'INFO'},
        'tool': {'level': 'INFO'},
        'websockets': {'level': 'WARNING'},
        'websockets.client': {'level': 'WARNING'},
        'websockets.server': {'level': 'WARNING'},
        'websockets.protocol': {'level': 'WARNING'}
    }
}
