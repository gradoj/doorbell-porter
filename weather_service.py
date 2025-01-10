"""
Weather Service Module for OpenWeatherMap Integration.

This module provides weather data retrieval and processing functionality:
- Current weather conditions
- Temperature and "feels like" temperature
- Humidity and wind information
- Extended data including:
  * Pressure
  * Visibility
  * Cloud cover
  * Sunrise/sunset times
  * Rain/snow data when available

The service uses OpenWeatherMap's API with metric units and includes:
- Error handling with retries
- Response validation
- Unit conversions
- Compass direction calculation
"""

import json
import requests
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Union, List
from .config import WEATHER_API_KEY

#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

# API Configuration
BASE_URL = "http://api.openweathermap.org/data/2.5/weather"
REQUEST_TIMEOUT = 10  # seconds
UNITS = "metric"

# Unit Conversion
MS_TO_KMH = 3.6      # Convert m/s to km/h
HPA_TO_KPA = 0.1     # Convert hPa to kPa
M_TO_KM = 0.001      # Convert meters to kilometers

# Wind Direction
WIND_DIRECTIONS = [
    'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'
]

# Time Format
TIME_FORMAT = '%H:%M'

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

# Configure logger
logger = logging.getLogger('tool')

#------------------------------------------------------------------------------
# Weather Service Class
#------------------------------------------------------------------------------

class WeatherService:
    """
    Handles weather data retrieval and processing from OpenWeatherMap API.
    
    This class manages:
    - API communication
    - Data processing and formatting
    - Error handling and retries
    - Unit conversions
    
    Attributes:
        api_key (str): OpenWeatherMap API key
    """
    
    def __init__(self):
        """
        Initialize the weather service.
        
        Raises:
            ValueError: If OPENWEATHER_API_KEY is not set
        """
        if not WEATHER_API_KEY:
            raise ValueError("Missing OPENWEATHER_API_KEY in environment variables")
        self.api_key = WEATHER_API_KEY
        
    def get_weather(self, lat: float, lon: float, max_retries: int = 3) -> str:
        """
        Get current weather conditions for given coordinates.
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            max_retries: Maximum number of API retry attempts
            
        Returns:
            Formatted weather information string
            
        Raises:
            ValueError: If coordinates are invalid
            requests.RequestException: If API request fails
            json.JSONDecodeError: If API response is invalid
        """
        try:
            logger.info(f"Weather tool called for coordinates: lat={lat}, lon={lon}")
            
            # Validate coordinates
            try:
                lat_float = float(lat)
                lon_float = float(lon)
            except ValueError as e:
                error = f"Invalid coordinates: {e}"
                logger.error(error)
                return error

            # Build API URL
            weather_url = (f"{BASE_URL}?"
                         f"lat={lat_float}&"
                         f"lon={lon_float}&"
                         f"appid={self.api_key}&"
                         f"units={UNITS}")

            # Make API request
            try:
                weather_response = requests.get(weather_url, timeout=REQUEST_TIMEOUT)
                weather_data = weather_response.json()
            except requests.Timeout:
                error = "Weather API request timed out"
                logger.error(error)
                return error
            except requests.RequestException as e:
                error = f"Weather API request failed: {e}"
                logger.error(error)
                return error
            except json.JSONDecodeError as e:
                error = f"Invalid JSON response from weather API: {e}"
                logger.error(error)
                return error
            
            if weather_response.status_code == 200:
                logger.debug(f"Raw weather data: {json.dumps(weather_data, indent=2)}")
                return self._format_weather_data(weather_data, lat, lon)
            else:
                error_msg = f"Error getting weather: {weather_data.get('message', 'Unknown error')}"
                logger.error(error_msg)
                return error_msg
                
        except Exception as e:
            error_msg = f"Error in weather tool: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def _format_weather_data(self, weather_data: Dict[str, Any], lat: float, lon: float) -> str:
        """
        Format weather data into human-readable string.
        
        Args:
            weather_data: Raw weather data from API
            lat: Latitude for location name fallback
            lon: Longitude for location name fallback
            
        Returns:
            Formatted weather information string
        """
        # Basic weather data
        temp = round(weather_data['main']['temp'])
        feels_like = round(weather_data['main']['feels_like'])
        humidity = weather_data['main']['humidity']
        description = weather_data['weather'][0]['description']
        name = weather_data.get('name', f"coordinates ({lat}, {lon})")

        # Wind data
        wind_speed_ms = weather_data['wind'].get('speed', 0)
        wind_speed_kmh = round(wind_speed_ms * MS_TO_KMH)
        wind_deg = weather_data['wind'].get('deg', 0)

        # Convert wind direction to compass
        index = round(wind_deg / (360 / len(WIND_DIRECTIONS))) % len(WIND_DIRECTIONS)
        wind_dir = WIND_DIRECTIONS[index]

        # Basic weather info (always shown)
        weather_info = (
            f"Current weather in {name}: {description}, "
            f"temperature: {temp}°C (feels like {feels_like}°C), "
            f"humidity: {humidity}%, "
            f"wind: {wind_speed_kmh} km/h {wind_dir}"
        )

        # Get extended data if available
        extended_data = self._get_extended_data(weather_data)
        if extended_data:
            weather_info += "\n\nExtended weather data:\n" + "\n".join(extended_data)
        
        logger.info(f"Weather info: {weather_info}")
        return weather_info

    def _get_extended_data(self, weather_data: Dict[str, Any]) -> List[str]:
        """
        Extract extended weather data from API response.
        
        Args:
            weather_data: Raw weather data from API
            
        Returns:
            List of formatted extended data strings
        """
        extended_data = []

        # Pressure
        if 'pressure' in weather_data['main']:
            pressure_hpa = weather_data['main']['pressure']
            pressure_kpa = round(pressure_hpa * HPA_TO_KPA, 1)
            extended_data.append(f"Pressure: {pressure_kpa} kPa")

        # Visibility
        if 'visibility' in weather_data:
            visibility_km = round(weather_data['visibility'] * M_TO_KM, 1)
            extended_data.append(f"Visibility: {visibility_km} km")

        # Cloud cover
        if 'clouds' in weather_data and 'all' in weather_data['clouds']:
            clouds = weather_data['clouds']['all']
            extended_data.append(f"Cloud cover: {clouds}%")

        # Sunrise/Sunset times
        if 'sys' in weather_data:
            if 'sunrise' in weather_data['sys']:
                sunrise = weather_data['sys']['sunrise']
                sunrise_time = datetime.fromtimestamp(sunrise).strftime(TIME_FORMAT)
                extended_data.append(f"Sunrise: {sunrise_time}")
            if 'sunset' in weather_data['sys']:
                sunset = weather_data['sys']['sunset']
                sunset_time = datetime.fromtimestamp(sunset).strftime(TIME_FORMAT)
                extended_data.append(f"Sunset: {sunset_time}")

        # Precipitation data
        extended_data.extend(self._get_precipitation_data(weather_data))

        return extended_data

    def _get_precipitation_data(self, weather_data: Dict[str, Any]) -> List[str]:
        """
        Extract precipitation (rain/snow) data from API response.
        
        Args:
            weather_data: Raw weather data from API
            
        Returns:
            List of formatted precipitation data strings
        """
        precipitation_data = []

        # Rain data
        if 'rain' in weather_data:
            if '1h' in weather_data['rain']:
                rain_1h = weather_data['rain']['1h']
                precipitation_data.append(f"Rain (last hour): {rain_1h} mm")
            if '3h' in weather_data['rain']:
                rain_3h = weather_data['rain']['3h']
                precipitation_data.append(f"Rain (last 3 hours): {rain_3h} mm")

        # Snow data
        if 'snow' in weather_data:
            if '1h' in weather_data['snow']:
                snow_1h = weather_data['snow']['1h']
                precipitation_data.append(f"Snow (last hour): {snow_1h} mm")
            if '3h' in weather_data['snow']:
                snow_3h = weather_data['snow']['3h']
                precipitation_data.append(f"Snow (last 3 hours): {snow_3h} mm")

        return precipitation_data
