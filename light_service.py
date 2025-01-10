"""
Light Service Module for LED Control.

This module provides functionality to control LED lights using flux_led:
- Turn light on/off
- Error handling and logging
- Connection management
"""

import logging
import os
from typing import Optional
from flux_led import WifiLedBulb
try:
    from . import config
except ImportError:
    config = None

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('tool')

#------------------------------------------------------------------------------
# Light Service Class
#------------------------------------------------------------------------------

class LightService:
    """
    Handles LED light control operations.
    
    This class manages:
    - Light connection
    - On/off control
    - Error handling
    
    Attributes:
        ip (str): Light IP address
    """
    
    def __init__(self):
        """
        Initialize the light service.
        
        Raises:
            ValueError: If LED_IP is not set
        """
        if config and hasattr(config, 'LED_IP'):
            self.ip = config.LED_IP
        else:
            self.ip = os.getenv('LED_IP')
        if not self.ip:
            raise ValueError("Missing LED_IP in environment variables")
        
    def _get_light(self) -> Optional[WifiLedBulb]:
        """
        Create connection to LED light.
        
        Returns:
            WifiLedBulb instance or None if connection fails
            
        Raises:
            Exception: If connection fails
        """
        try:
            return WifiLedBulb(self.ip)
        except Exception as e:
            logger.error(f"Error connecting to light: {str(e)}")
            return None
            
    def turn_on(self) -> str:
        """
        Turn the light on.
        
        Returns:
            Status message
        """
        try:
            light = self._get_light()
            if light:
                light.turnOn()
                logger.info("Light turned on successfully")
                return "Light turned on"
            return "Failed to connect to light"
        except Exception as e:
            error_msg = f"Error turning light on: {str(e)}"
            logger.error(error_msg)
            return error_msg
            
    def turn_off(self) -> str:
        """
        Turn the light off.
        
        Returns:
            Status message
        """
        try:
            light = self._get_light()
            if light:
                light.turnOff()
                logger.info("Light turned off successfully")
                return "Light turned off"
            return "Failed to connect to light"
        except Exception as e:
            error_msg = f"Error turning light off: {str(e)}"
            logger.error(error_msg)
            return error_msg

#------------------------------------------------------------------------------
# Main
#------------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    import time

    # Load environment variables
    load_dotenv()
    
    # Create light service
    light = LightService()
    
    # Test light control
    print("Turning light on...")
    print(light.turn_on())
    
    time.sleep(2)  # Wait 2 seconds
    
    print("\nTurning light off...")
    print(light.turn_off())
