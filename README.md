# Doorbell Porter

A smart AI-powered doorbell intercom system that acts as a virtual porter, providing professional greetings, two-way communication, and helpful information including weather updates. The system combines OpenAI's realtime API with a Reolink doorbell for two-way audio and camera functionality, plus automated light control for better visibility in dark conditions.

This is an AI learning project exploring the capabilities of OpenAI's realtime API for natural conversations and vision analysis, while integrating with real-world IoT devices.

## System Architecture

```
┌──────────┐     ┌───────────────┐     ┌──────────────┐
│  Person  │◄────┤   Doorbell    │────►│  Application │
└──────────┘     │  (Reolink)    │     │              │
    Audio        └───────────────┘     │   ┌────────┐ │
    Video              RTSP            │   │ Tools  │ │
                                       │   └────────┘ │
                                       │              │
                                       │   ┌────────┐ │     ┌───────────┐
                                       │   │Weather │ │────►│OpenWeather│
                                       │   │Service │ │     │   API     │
                                       │   └────────┘ │     └───────────┘
                                       │              │
                                       │   ┌────────┐ │     ┌───────────┐
                                       │   │  AI    │ │────►│  OpenAI   │
                                       │   │Service │ │     │Realtime   │
                                       │   └────────┘ │     │   API     │
                                       │              │     └───────────┘
                                       │   ┌────────┐ │
                                       │   │ Light  │ │────►┌───────────┐
                                       │   │Service │ │     │   LED     │
                                       │   └────────┘ │     │  Light    │
                                       └──────────────┘     └───────────┘
```

## Features

Core Features (Required):
- Two-way audio communication through Reolink doorbell
- Webhook server for doorbell events
- Professional AI porter/assistant responses

Optional Features (Configurable):
- Weather Information:
  * Real-time weather data via OpenWeatherMap
  * Temperature, humidity, wind conditions
  * Extended data: pressure, visibility, cloud cover
- Vision Features:
  * Automatic snapshot capture on events
  * OpenAI Vision analysis of visitors
  * Configurable resolution (default: 640x480)
- Light Control:
  * Magic Home LED control via flux_led
  * Automatic activation in low light
  * Basic on/off functionality

## Known Issues

1. Audio Processing:
   - FFmpeg backchannel path is currently non-functional (use audioop path instead)
   - Occasional audio artifacts during rapid speech transitions

Workarounds:
   - Use `USE_FFMPEG_BACKCHANNEL = False` in config.py (default setting)

## AI Tools

The system provides several AI-powered tools:

### Voice Communication (Required)
- `connect_voice`: Establishes two-way voice communication
- `disconnect_voice`: Ends voice communication session
- Handles natural pauses and turn-taking in conversation
- Optimized for low-latency with 200ms buffer

### Vision Analysis (Optional)
- `take_snapshot`: Captures images from doorbell camera
- `analyze_snapshot`: Uses vision AI to analyze visitors and scenes
- Provides detailed descriptions of what the camera sees

### Weather Information (Optional)
- `get_weather`: Retrieves detailed weather data
- Provides current conditions, temperature, humidity, wind
- Includes extended data like pressure, visibility, cloud cover

### Light Control (Optional)
- `turn_light_on`: Activates LED light when needed
- `turn_light_off`: Deactivates LED light
- Automatically manages lighting for better visibility

## System Requirements

### Hardware
- Reolink doorbell camera with RTSP support
- Network connectivity for webhook server
- Magic Home compatible LED light (optional)

### Software
- Python 3.8+
- FFmpeg for audio/video processing

### API Keys
- OpenAI API key (required)
- OpenWeather API key (optional)

## Project Structure

```
doorbell_porter_weather/
├── main.py              # Main application entry point
├── config.py            # Configuration and feature toggles
├── audio_handler.py     # Doorbell audio streaming
├── camera.py           # Camera and snapshot management
├── doorbell_handler.py  # Doorbell and webhook management
├── image_analyzer.py    # Vision AI analysis
├── weather_service.py   # Weather API integration
├── light_service.py    # Magic Home LED control
├── tools.py            # OpenAI tool implementations
├── rtsp_session.py     # RTSP session management
├── requirements.txt    # Package dependencies
├── .env.example        # Environment variable template
└── README.md          # Project documentation
```

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/gradoj/doorbell-porter.git
cd doorbell-porter
```

### 2. Set Up Python Environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Unix/macOS:
source venv/bin/activate
```

### 3. Install Dependencies

The project requires several Python packages:

#### Core Dependencies
```bash
pip install \
    websockets==12.0 \
    aiohttp==3.9.1 \
    requests==2.31.0 \
    openai==1.6.0 \
    python-dotenv==1.0.0 \
    pytz==2023.3.post1 \
    typing-extensions==4.8.0 \
    flux_led==0.28.0

# Or install everything at once
pip install -r requirements.txt
```

#### System Dependencies
Install FFmpeg:
```bash
# Windows (using chocolatey):
choco install ffmpeg

# macOS:
brew install ffmpeg

# Linux:
sudo apt-get install ffmpeg  # Debian/Ubuntu
sudo yum install ffmpeg      # CentOS/RHEL
```

### 4. Configure Environment
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your credentials:
   ```
   # Required Settings
   OPENAI_API_KEY=your_openai_key_here
   DOORBELL_URL=rtsp://your_camera_ip:554/path
   DOORBELL_USERNAME=your_username
   DOORBELL_PASSWORD=your_password
   WEBHOOK_HOST=your_webhook_host
   WEBHOOK_PORT=your_webhook_port

   # Optional Settings (based on enabled features)
   OPENWEATHER_API_KEY=your_weather_key_here  # For weather feature
   LED_IP=your_led_ip_here                    # For light control
   ```

## Configuration

### Feature Configuration
Enable/disable optional features in `config.py`:
```python
FEATURES = {
    'WEATHER': True,        # OpenWeatherMap integration
    'LIGHT_CONTROL': True,  # Magic Home LED control
    'VISION': True,         # Camera vision features
}
```

### Basic Configuration
Update settings in `config.py`:
- Audio settings (channels, rate, chunk size)
- Camera settings (resolution, snapshot options)
- Weather settings (default location)
- Logging configuration

### Advanced Configuration
- FFmpeg options in `camera.py`
- Audio processing parameters in `audio_handler.py`
- Vision model settings in `image_analyzer.py`
- Weather API options in `weather_service.py`
- LED light options in `light_service.py`

## Usage

### Running the Application
```bash
python main.py
```

The system will:
1. Start the webhook server for doorbell events
2. Initialize the doorbell audio handler
3. Connect to OpenAI's realtime API
4. Begin processing audio and responding to events

## Development

### Setting Up Development Environment
```bash
# Install all dependencies including development tools
pip install -r requirements.txt

# Run tests
pytest
```

## Future Improvements

### Local Model Integration
- Integrate local LLM alternatives
- Add local speech-to-text capabilities
- Implement offline fallback modes
- Reduce API dependencies
- Adding memories

### Audio Processing
- Implement alternative to FFmpeg backchannel
- Add advanced noise reduction
- Improve echo cancellation
- Optimize audio compression
- Implement automatic gain control

### Camera Integration
- Add support for other camera brands
- Implement ONVIF standard support
- Add motion detection capabilities
- Improve snapshot quality options

### Light Control
- Add support for brightness control
- Implement color changing capabilities
- Add support for multiple light zones
- Integrate with other smart light protocols

### User Interface
- Add web interface for configuration
- Implement status dashboard
- Add real-time audio level monitoring
- Provide configuration GUI

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- OpenAI for realtime API
- OpenWeather for weather data
- Reolink for camera integration
- FFmpeg for media processing
- go2rtc for RTSP streaming techniques
- HappyTime RTSP project for audio handling patterns
- Various open-source ONVIF implementations
- Magic Home protocol for LED control
