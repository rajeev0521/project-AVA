# AVA - Voice-Based AI Calendar Assistant

AVA is a voice-controlled AI assistant that helps manage your Google Calendar through natural language commands. It's designed to make calendar management more accessible and intuitive using voice interactions.

## Features

- Wake word detection ("Hey AVA")
- Natural language processing for calendar operations
- Google Calendar integration
- Real-time voice processing
- Google OAuth authentication
- Docker containerization

## Prerequisites

- Python 3.8 or higher
- Google Cloud Platform account
- Google Calendar API enabled
- Docker (for containerized deployment)

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up Google Cloud credentials:
   - Create a project in Google Cloud Console
   - Enable Google Calendar API
   - Download OAuth 2.0 credentials
   - Save as `credentials.json` in the project root

4. Setup Gemini API
   - Create a Gemini account
   - Get your Gemini API key


5. Create a `.env` file with your configuration:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=credentials.json
   GEMINI_API_KEY=GEMINI_API_KEY
   PORCUPINE_ACCESS_KEY=PORCUPINE_ACCESS_KEY
   ```

## Usage

1. Run the application:
   ```bash
   python main.py
   ```

2. Say "Hey AVA" to activate the assistant
3. Speak your calendar command, for example:
   - "Schedule a meeting tomorrow at 2 PM"
   - "What's on my calendar for next week?"
   - "Add a reminder for my birthday"

## Project Structure

```
ava/
├── main.py              # Main application entry point
├── voice_processor.py   # Voice processing and wake word detection
├── calendar_manager.py  # Google Calendar integration
├── nlp_processor.py     # Natural language processing
├── auth_manager.py      # Google OAuth authentication
```

## Docker Deployment

Build and run with Docker:
```bash
docker build -t ava-assistant .
docker run -it ava-assistant
```

## Contributing

Feel free to submit issues and enhancement requests!
