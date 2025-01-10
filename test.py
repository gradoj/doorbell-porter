"""
Test script to verify the Doorbell Porter installation and functionality.
"""

import asyncio
import logging
from .main import DoorbellPorterApp
from .config import OPENAI_API_KEY, WEATHER_API_KEY

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_installation():
    """Test the installation and configuration"""
    
    # Check environment variables
    logger.info("Checking environment variables...")
    if not OPENAI_API_KEY:
        logger.error("❌ OPENAI_API_KEY not found in environment")
        return False
    logger.info("✓ OPENAI_API_KEY found")
    
    if not WEATHER_API_KEY:
        logger.error("❌ OPENWEATHER_API_KEY not found in environment")
        return False
    logger.info("✓ OPENWEATHER_API_KEY found")
    
    # Test application initialization
    logger.info("Testing application initialization...")
    try:
        app = DoorbellPorterApp()
        logger.info("✓ Application initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        return False
    
    # Test webhook server
    logger.info("Testing webhook server...")
    try:
        await app.doorbell_handler.start_webhook_server()
        logger.info("✓ Webhook server started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start webhook server: {e}")
        return False
    
    # Test weather service
    logger.info("Testing weather service...")
    try:
        weather_result = app.tool_manager.weather_service.get_weather(51.5074, -0.1278)  # London coordinates
        if "Error" in weather_result:
            logger.error(f"❌ Weather service error: {weather_result}")
            return False
        logger.info("✓ Weather service working")
        logger.info(f"Sample weather data: {weather_result}")
    except Exception as e:
        logger.error(f"❌ Failed to test weather service: {e}")
        return False
    
    # Test snapshot functionality
    logger.info("Testing snapshot functionality...")
    try:
        snapshot_result = app.tool_manager.handle_tool_call(None, {
            "type": "response.function_call_arguments.done",
            "name": "take_snapshot",
            "arguments": '{"resolution": "640x480"}'
        })
        logger.info("✓ Snapshot functionality available")
    except Exception as e:
        logger.error(f"❌ Failed to test snapshot functionality: {e}")
        return False
    
    logger.info("\n✓ All tests completed successfully!")
    return True

def main():
    """Run the test suite"""
    logger.info("Starting Doorbell Porter test suite...")
    try:
        asyncio.run(test_installation())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with error: {e}")

if __name__ == "__main__":
    main()
