"""
Doorbell Handler Module for Event Management.

This module provides functionality for managing doorbell interactions including:
- Webhook server for doorbell events
- Audio communication handling
- Event callback management
- Snapshot capture integration

The handler manages:
1. Webhook Server:
   - Listens for doorbell press events
   - Processes incoming webhook data
   - Triggers appropriate responses

2. Audio Communication:
   - Initializes two-way audio
   - Manages audio streaming
   - Handles cleanup

3. Event Processing:
   - Queues doorbell events
   - Executes callback functions
   - Integrates with camera snapshots

4. Error Handling:
   - Connection management
   - Resource cleanup
   - Logging and monitoring
"""

import asyncio
import logging
from datetime import datetime
from aiohttp import web
from typing import Callable, Awaitable, Optional, Dict, Any, Union
from .audio_handler import DoorbellAudioHandler
from .camera import take_snapshot
from .config import (
    DOORBELL_URL,
    DOORBELL_USERNAME,
    DOORBELL_PASSWORD,
    WEBHOOK_HOST,
    WEBHOOK_PORT
)

#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

# Webhook Configuration
WEBHOOK_ROUTE = '/doorbell'
CONTENT_TYPE_JSON = 'application/json'

# Event Configuration
SNAPSHOT_RESOLUTION = "640x480"
TIME_FORMAT = "%I:%M %p"

# Event Template
EVENT_PROMPT_TEMPLATE = """Event: {message}

Please greet the visitor and assist them. A snapshot will be taken automatically. You should:
1. Call connect_voice to establish two-way communication
2. Greet them warmly and professionally
3. Ask how you can help them
4. Review the snapshot when it's available to better assist the visitor"""

#------------------------------------------------------------------------------
# Logger Configuration
#------------------------------------------------------------------------------

# Configure loggers
logger = logging.getLogger('app')
doorbell_logger = logging.getLogger('doorbell')

#------------------------------------------------------------------------------
# Doorbell Handler Class
#------------------------------------------------------------------------------

class DoorbellEventHandler:
    """
    Handles doorbell events and webhook server.
    
    This class manages:
    - Webhook server for doorbell events
    - Audio communication
    - Event callbacks
    - Snapshot integration
    
    Attributes:
        doorbell_events (asyncio.Queue): Queue for doorbell events
        doorbell (Optional[DoorbellAudioHandler]): Audio handler instance
        audio_handler (Optional[DoorbellAudioHandler]): Audio handler instance
        event_callback (Optional[Callable]): Callback for doorbell events
    """
    
    def __init__(self):
        """Initialize doorbell event handler."""
        self.doorbell_events: asyncio.Queue = asyncio.Queue()
        self.doorbell: Optional[DoorbellAudioHandler] = None
        self.audio_handler: Optional[DoorbellAudioHandler] = None
        self.event_callback: Optional[Callable[[str], Awaitable[None]]] = None
        
    def initialize_doorbell(self) -> None:
        """
        Initialize the doorbell audio handler.
        
        This method:
        1. Creates audio handler instance
        2. Sets up connection parameters
        3. Initializes audio streaming
        
        Raises:
            ValueError: If connection parameters are invalid
            Exception: For other initialization errors
        """
        try:
            logger.info("Initializing doorbell audio handler...")
            self.audio_handler = DoorbellAudioHandler(
                url=DOORBELL_URL,
                username=DOORBELL_USERNAME,
                password=DOORBELL_PASSWORD
            )
            self.doorbell = self.audio_handler  # For backward compatibility
            logger.info("Doorbell audio handler initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize doorbell: {e}")
            raise
        
    def set_event_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Set callback for doorbell events.
        
        Args:
            callback: Async function to call with event message
                     Function should accept a string parameter and return None
        
        Raises:
            TypeError: If callback is not a callable or is not async
        """
        if not callable(callback):
            raise TypeError("Event callback must be callable")
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError("Event callback must be async")
        self.event_callback = callback
        
    async def handle_webhook(self, request: web.Request) -> web.Response:
        """
        Handle webhook requests from the doorbell.
        
        This method:
        1. Processes incoming webhook data
        2. Extracts event information
        3. Takes snapshot if possible
        4. Triggers event callback
        
        Args:
            request: Incoming webhook request
            
        Returns:
            HTTP response
            
        Raises:
            web.HTTPBadRequest: If request data is invalid
            Exception: For other processing errors
        """
        try:
            # Log event details
            event_time = datetime.now()
            logger.info(f"\n=== Doorbell Event at {event_time} ===")
            logger.info(f"Method: {request.method}")
            logger.info(f"Headers: {dict(request.headers)}")
            
            # Parse request data
            try:
                if request.content_type == CONTENT_TYPE_JSON:
                    data = await request.json()
                else:
                    data = await request.text()
                logger.info(f"Data: {data}")
            except Exception as e:
                logger.error(f"Error parsing request data: {e}")
                raise web.HTTPBadRequest(text=str(e))
            
            # Extract event message
            event_message = self._extract_event_message(data, event_time)
            
            # Create event prompt
            prompt = EVENT_PROMPT_TEMPLATE.format(message=event_message)
            
            # Take snapshot
            snapshot_result = await self._take_event_snapshot()
            if snapshot_result:
                prompt += f"\n\nA snapshot has been automatically taken: {snapshot_result}"
            
            # Process event
            await self._process_event(prompt)
            
            return web.Response(text="OK")
            
        except web.HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            raise web.HTTPInternalServerError(text=str(e))

    def _extract_event_message(self, data: Union[Dict[str, Any], str], 
                             event_time: datetime) -> str:
        """
        Extract event message from webhook data.
        
        Args:
            data: Webhook request data
            event_time: Event timestamp
            
        Returns:
            Formatted event message
        """
        # Extract alarm info if available
        event_message = "Someone pressed the doorbell"
        if isinstance(data, dict) and 'alarm' in data:
            alarm = data['alarm']
            if 'message' in alarm:
                event_message = alarm['message']
            if 'deviceModel' in alarm:
                event_message += f" ({alarm['deviceModel']})"
        
        # Add timestamp
        return f"{event_message} at {event_time.strftime(TIME_FORMAT)}"

    async def _take_event_snapshot(self) -> Optional[str]:
        """
        Take snapshot for doorbell event.
        
        Returns:
            Path to snapshot if successful, None otherwise
        """
        try:
            snapshot_result = take_snapshot(SNAPSHOT_RESOLUTION)
            if snapshot_result and not snapshot_result.startswith("Error"):
                return snapshot_result
        except Exception as e:
            logger.error(f"Error taking snapshot: {e}")
        return None

    async def _process_event(self, prompt: str) -> None:
        """
        Process doorbell event.
        
        Args:
            prompt: Event prompt message
            
        Raises:
            Exception: If event processing fails
        """
        try:
            # Add event to queue
            await self.doorbell_events.put(prompt)
            
            # Execute callback if set
            if self.event_callback:
                try:
                    await self.event_callback(prompt)
                except Exception as e:
                    logger.error(f"Error in event callback: {e}")
                    raise
                    
        except Exception as e:
            logger.error(f"Error processing event: {e}")
            raise

    async def start_webhook_server(self) -> None:
        """
        Start the webhook server.
        
        This method:
        1. Creates aiohttp application
        2. Sets up webhook route
        3. Starts server on configured host/port
        
        Raises:
            Exception: If server fails to start
        """
        try:
            app = web.Application()
            app.router.add_route('*', WEBHOOK_ROUTE, self.handle_webhook)
            
            runner = web.AppRunner(app)
            await runner.setup()
            
            site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
            await site.start()
            
            logger.info(f"Webhook server started on {WEBHOOK_HOST}:{WEBHOOK_PORT}")
            
        except Exception as e:
            logger.error(f"Failed to start webhook server: {e}")
            raise

    def cleanup(self) -> None:
        """
        Clean up doorbell resources.
        
        This method:
        1. Stops audio streaming
        2. Closes connections
        3. Releases resources
        """
        try:
            if self.audio_handler:
                self.audio_handler.cleanup()
                logger.info("Doorbell resources cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
