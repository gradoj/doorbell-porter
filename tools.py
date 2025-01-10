"""
Tools Module for OpenAI Function Implementations.

This module provides tool definitions and handlers for the AI assistant's capabilities:

Tools:
1. get_datetime: Provides current date/time in Denver timezone
2. analyze_snapshot: Analyzes doorbell camera snapshots using vision AI
3. take_snapshot: Captures images from the doorbell camera
4. get_weather: Retrieves weather information for specified locations
5. connect_voice: Establishes two-way voice communication
6. disconnect_voice: Ends voice communication sessions

Each tool includes:
- OpenAI function definition
- Parameter validation
- Error handling
- Retry logic where appropriate
- Logging for debugging
"""

import json
import logging
import asyncio
from datetime import datetime
import pytz
from typing import Dict, Any, List, Optional, Union, Tuple

from .weather_service import WeatherService
from .camera import take_snapshot
from .image_analyzer import ImageAnalyzer
from .light_service import LightService
from .config import OPENAI_API_KEY, DEFAULT_LOCATION

#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

WEATHER_RETRY_ATTEMPTS = 3
WEATHER_RETRY_DELAYS = [2, 4]  # Seconds between retries
DISCONNECT_DELAY = 2  # Seconds to wait before disconnecting voice
DENVER_TIMEZONE = 'America/Denver'

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

# Configure loggers
logger = logging.getLogger('app')
tool_logger = logging.getLogger('tool')

#------------------------------------------------------------------------------
# Tool Manager Class
#------------------------------------------------------------------------------

class ToolManager:
    """
    Manages OpenAI tool definitions and handlers.
    
    This class centralizes all tool-related functionality including:
    - Tool definitions for OpenAI
    - Tool execution logic
    - Response handling
    - Error management
    
    Attributes:
        weather_service (WeatherService): Service for weather data
        doorbell_handler (Any): Handler for doorbell interactions
        image_analyzer (ImageAnalyzer): Service for image analysis
    """
    
    def __init__(self, doorbell_handler: Optional[Any] = None):
        """
        Initialize tool manager with required services.
        
        Args:
            doorbell_handler: Optional doorbell handler for snapshots and audio
        """
        self.weather_service = WeatherService()
        self.doorbell_handler = doorbell_handler
        self.image_analyzer = ImageAnalyzer(OPENAI_API_KEY)
        self.light_service = LightService()
        
    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get list of tool definitions for OpenAI.
        
        Returns:
            List of tool definitions in OpenAI function calling format
        """
        return [{
            "type": "function",
            "name": "get_datetime",
            "description": "Get the current local date and time",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "Optional format: 'time' for time only, 'date' for date only, or 'full' for both",
                        "enum": ["time", "date", "full"]
                    }
                }
            }
        }, {
            "type": "function",
            "name": "analyze_snapshot",
            "description": "Analyze a snapshot from the doorbell camera using vision model",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Path to the snapshot image"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional custom prompt for analysis"
                    }
                },
                "required": ["image_path"]
            }
        }, {
            "type": "function",
            "name": "take_snapshot",
            "description": "Take a snapshot from the doorbell camera",
            "parameters": {
                "type": "object",
                "properties": {
                    "resolution": {
                        "type": "string",
                        "description": "Optional resolution in format WIDTHxHEIGHT (e.g. 640x480)"
                    }
                }
            }
        }, {
            "type": "function",
            "name": "get_weather",
            "description": "Get current weather information. Uses default location if coordinates not provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Optional latitude coordinate"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Optional longitude coordinate"
                    }
                }
            }
        }, {
            "type": "function",
            "name": "connect_voice",
            "description": "Establishes two-way voice communication with the doorbell when button is pressed",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }, {
            "type": "function",
            "name": "disconnect_voice",
            "description": "Disconnects the two-way voice communication. Only use this when the user specifically says 'goodbye', 'end call', or explicitly asks to end the conversation. Do not use this when the user is just speaking normally during the conversation.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }, {
            "type": "function",
            "name": "turn_light_on",
            "description": "Turn on the LED light. Useful when it's dark and someone is at the door.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }, {
            "type": "function",
            "name": "turn_light_off",
            "description": "Turn off the LED light when it's no longer needed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }]

    async def handle_tool_call(self, websocket: Any, response: Dict[str, Any]) -> None:
        """
        Handle tool calls from OpenAI.
        
        Args:
            websocket: WebSocket connection to OpenAI
            response: Tool call response from OpenAI containing:
                - name: Tool name
                - arguments: Tool arguments
                - call_id: Unique call identifier
        
        Raises:
            Exception: For any errors during tool execution
        """
        try:
            tool_logger.info(f"Tool call received: {json.dumps(response, indent=2)}")
            
            # Extract tool arguments
            args_str = ''.join(response.get('arguments', []))
            tool_logger.debug(f"Raw arguments: {args_str}")
            
            # Parse arguments with improved error handling
            args_data = self._parse_tool_arguments(args_str)
            
            # Get tool result with retry logic
            result = await self._execute_tool(response.get('name'), args_data)

            # Send responses
            await self._send_tool_responses(websocket, response["call_id"], result)
            
        except Exception as e:
            error_msg = f"Error handling tool call: {str(e)}"
            tool_logger.error(error_msg)
            await self._send_error_response(websocket, error_msg)
            
    def _parse_tool_arguments(self, args_str: str) -> Dict[str, Any]:
        """
        Parse tool arguments with improved error handling.
        
        Args:
            args_str: Raw argument string from OpenAI
            
        Returns:
            Parsed arguments dictionary
            
        Raises:
            ValueError: If arguments cannot be parsed
        """
        try:
            # First try parsing as-is
            return json.loads(args_str)
        except json.JSONDecodeError:
            try:
                # If that fails, try to fix common JSON issues
                if '"lat":' in args_str and '"lon":' in args_str:
                    # Extract lat and lon values using string manipulation
                    lat_start = args_str.find('"lat":') + 6
                    lat_end = args_str.find('"lon":', lat_start)
                    lon_start = args_str.find('"lon":') + 6
                    lon_end = args_str.find('}', lon_start)
                    
                    if lat_end == -1:  # If lon comes before lat
                        lat_end = args_str.find('}', lat_start)
                    
                    lat_str = args_str[lat_start:lat_end].strip().rstrip(',')
                    lon_str = args_str[lon_start:lon_end].strip()
                    
                    # Construct proper JSON
                    fixed_args = f'{{"lat": {lat_str}, "lon": {lon_str}}}'
                    tool_logger.debug(f"Fixed JSON arguments: {fixed_args}")
                    return json.loads(fixed_args)
                else:
                    raise ValueError("Could not fix JSON format")
            except Exception as e:
                tool_logger.error(f"JSON parsing error: {e}")
                tool_logger.error(f"Original arguments: {args_str}")
                raise ValueError(f"Failed to parse tool arguments: {e}")
    
    async def _execute_tool(self, function_name: str, args_data: Dict[str, Any]) -> str:
        """
        Execute tool with retry logic.
        
        Args:
            function_name: Name of the tool to execute
            args_data: Parsed tool arguments
            
        Returns:
            Tool execution result message
            
        Raises:
            Exception: For tool execution errors
        """
        tool_logger.info(f"Executing tool: {function_name} with args: {args_data}")
        
        if function_name == 'take_snapshot':
            return await self._handle_snapshot(args_data)
            
        elif function_name == 'get_datetime':
            return self._handle_datetime(args_data)
                
        elif function_name == 'get_weather':
            return await self._handle_weather(args_data)
                
        elif function_name == 'analyze_snapshot':
            return self._handle_analysis(args_data)
                
        elif function_name == 'connect_voice':
            return self._handle_voice_connect()
                
        elif function_name == 'disconnect_voice':
            return await self._handle_voice_disconnect()
                
        elif function_name == 'turn_light_on':
            return self._handle_light_on()
                
        elif function_name == 'turn_light_off':
            return self._handle_light_off()
                
        else:
            error = f"Error: Unknown tool {function_name}"
            tool_logger.error(error)
            return error
            
    def _handle_light_on(self) -> str:
        """Handle turning the light on."""
        try:
            return self.light_service.turn_on()
        except Exception as e:
            error = f"Error turning light on: {str(e)}"
            tool_logger.error(error)
            return error
            
    def _handle_light_off(self) -> str:
        """Handle turning the light off."""
        try:
            return self.light_service.turn_off()
        except Exception as e:
            error = f"Error turning light off: {str(e)}"
            tool_logger.error(error)
            return error

    async def _handle_snapshot(self, args_data: Dict[str, Any]) -> str:
        """Handle snapshot capture and analysis."""
        resolution = args_data.get('resolution')
        snapshot_result = take_snapshot(resolution)
        tool_logger.info(f"Snapshot result: {snapshot_result}")
        
        if not snapshot_result.startswith("Error"):
            try:
                analysis = self.image_analyzer.analyze_snapshot(snapshot_result)
                tool_logger.info(f"Snapshot analysis: {analysis}")
                return f"Snapshot saved to {snapshot_result}\n\nAnalysis: {analysis}"
            except Exception as e:
                tool_logger.error(f"Error analyzing snapshot: {e}")
                return f"Snapshot saved to {snapshot_result}\n\nError analyzing image: {str(e)}"
        
        return snapshot_result

    def _handle_datetime(self, args_data: Dict[str, Any]) -> str:
        """Handle datetime requests."""
        try:
            format_type = args_data.get('format', 'full')
            tz = pytz.timezone(DENVER_TIMEZONE)
            now = datetime.now(tz)
            
            if format_type == 'time':
                return f"The current time is {now.strftime('%I:%M %p')}"
            elif format_type == 'date':
                return f"Today's date is {now.strftime('%A, %B %d, %Y')}"
            else:  # full
                return f"It is {now.strftime('%A, %B %d, %Y at %I:%M %p')}"
        except Exception as e:
            error = f"Error getting date/time: {str(e)}"
            tool_logger.error(error)
            return error

    async def _handle_weather(self, args_data: Dict[str, Any]) -> str:
        """Handle weather requests with retry logic."""
        lat = args_data.get('lat', DEFAULT_LOCATION['lat'])
        lon = args_data.get('lon', DEFAULT_LOCATION['lon'])
        location_name = DEFAULT_LOCATION['name'] if lat == DEFAULT_LOCATION['lat'] else "this location"
        
        for attempt in range(WEATHER_RETRY_ATTEMPTS):
            try:
                result = self.weather_service.get_weather(lat, lon)
                tool_logger.info(f"Weather result (attempt {attempt + 1}): {result}")
                return f"The weather in {location_name}: {result}"
            except Exception as e:
                if attempt < len(WEATHER_RETRY_DELAYS):
                    delay = WEATHER_RETRY_DELAYS[attempt]
                    tool_logger.warning(f"Weather attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    raise

    def _handle_analysis(self, args_data: Dict[str, Any]) -> str:
        """Handle snapshot analysis."""
        image_path = args_data.get('image_path')
        prompt = args_data.get('prompt')
        try:
            result = self.image_analyzer.analyze_snapshot(image_path, prompt)
            tool_logger.info(f"Analysis result: {result}")
            return result
        except Exception as e:
            error = f"Error analyzing snapshot: {str(e)}"
            tool_logger.error(error)
            return error

    def _handle_voice_connect(self) -> str:
        """Handle voice connection requests."""
        if self.doorbell_handler and hasattr(self.doorbell_handler, 'audio_handler'):
            try:
                self.doorbell_handler.audio_handler.start_recording()
                return "Two-way voice communication established."
            except Exception as e:
                error = f"Failed to establish voice communication: {str(e)}"
                tool_logger.error(error)
                return error
        else:
            return "No audio handler available for voice communication."

    async def _handle_voice_disconnect(self) -> str:
        """Handle voice disconnection requests."""
        if self.doorbell_handler and hasattr(self.doorbell_handler, 'audio_handler'):
            audio_handler = self.doorbell_handler.audio_handler
            
            # Clear any pending responses
            audio_handler.interrupt_playback()
            
            # Wait for initial delay to ensure message processing
            await asyncio.sleep(DISCONNECT_DELAY)
            
            # Now disconnect
            success = audio_handler.disconnect_audio()
            if success:
                # Return a unique message that won't trigger new responses
                return "Voice communication disconnected successfully - END"
            else:
                return "Failed to disconnect voice communication."
        else:
            return "No active voice communication to disconnect."
    
    async def _send_tool_responses(self, websocket: Any, call_id: str, result: str) -> None:
        """
        Send tool responses to OpenAI.
        
        Args:
            websocket: WebSocket connection
            call_id: Tool call ID
            result: Tool execution result
        """
        # Send immediate message response
        await websocket.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{
                    "type": "text",
                    "text": result
                }]
            }
        }))

        # Send tool output
        await websocket.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result
            }
        }))
        
        # Only create new response if not disconnecting
        if not result.endswith("- END"):
            await websocket.send(json.dumps({
                "type": "response.create"
            }))

    async def _send_error_response(self, websocket: Any, error_msg: str) -> None:
        """
        Send error response to OpenAI.
        
        Args:
            websocket: WebSocket connection
            error_msg: Error message to send
        """
        await websocket.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{
                    "type": "text",
                    "text": error_msg
                }]
            }
        }))
