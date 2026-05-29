# AVA - Voice-Activated AI Calendar Assistant

AVA is a high-performance, voice-activated AI assistant designed to manage Google Calendar events using natural language. Operating both as a local desktop service and a cloud-ready web application, AVA integrates local offline machine learning, advanced audio signal processing, long-term semantic memory, and a modern glassmorphic web interface.

---

## Key Technical Features

### 1. High-Fidelity Frontend Dashboard
*   **Modern Glassmorphic UI:** Built with pure HTML5, vanilla CSS3, and JavaScript, providing a smooth, responsive desktop control dashboard.
*   **Live Web Chat & Logs:** Interactive terminal widget for sending manual queries and monitoring real-time system logs and engine states.
*   **Calendar Integration:** Dynamic widget showing upcoming synchronized calendar schedules.

### 2. Multi-Mode Architecture
*   **Desktop Voice Loop:** Listens for the "Hey AVA" wake word, processes vocal input locally, and speaks responses asynchronously.
*   **FastAPI REST Server:** Exposes calendar mutations, short-term memory search, and rate-limited speech synthesis for web client environments.

### 3. Asynchronous & Resilient Speech Engine
*   **Threaded Speech Playback:** Non-blocking speech synthesis via pyttsx3 executed on daemon background threads, preventing interface lockups.
*   **Lazy Engine Loading:** Dynamic TTS engine initialization to prevent system crashes when host devices lack primary soundcards or audio drivers during application startup.

### 4. Local Offline Intent & Entity Processing
*   **SVM Intent Classification:** Uses a local Support Vector Machine (SVM) and TF-IDF vectorizer trained on predefined patterns, completing classification in milliseconds without remote LLM API calls.
*   **Pattern-Based Entity Extraction:** Local regular expression parsing for temporal ranges, dates, times, and calendar actions, conserving API quota and maximizing response speeds.

### 5. Advanced Audio Pipelines
*   **One-Time Noise Calibration:** Performs a single ambient audio calibration at startup, eliminating the latency of calibrating before every command.
*   **Whisper Optimization:** Loads the local OpenAI Whisper model once upon application startup instead of reloading it per transcription, reducing command execution times.

### 6. Relational & Semantic Memory
*   **Supabase Database Syncing:** Syncs events, user states, and conversational contexts to a PostgreSQL instance in Supabase.
*   **Bilingual Hinglish/English Generation:** Pre-generates responses within single LLM loops and provides local fallback prompts to support Hinglish and English context generation.

---

## Technical Architecture

```
project-AVA/
├── ava/
│   ├── __init__.py            # Module initialization and exports
│   ├── api.py                 # FastAPI service layer and API routes
│   ├── auth_manager.py        # Google OAuth 2.0 and token management
│   ├── calendar_manager.py    # Google Calendar API event mutations
│   ├── entity_extractor.py    # Local regex-based entity parsing
│   ├── intent_classifier.py   # Local SVM-based intent classification model
│   ├── logger.py              # Structured, rotating file/console logging
│   ├── main.py                # Command-Line loop and entry point
│   ├── memory_manager.py      # Thread-safe database state and memory syncing
│   ├── nlp_processor.py       # Bilingual fallbacks and LLM integration
│   ├── rate_limiter.py        # Token-bucket API protection middleware
│   ├── Speech_manager.py      # Threaded text-to-speech engine
│   ├── system_prompt.txt      # System instructions for LLM contexts
│   ├── training_data.json     # Local intent classification training patterns
│   └── voice_processor.py     # Ambient-calibrated Whisper and wake loop
├── frontend/
│   ├── index.html             # Dashboard markup structure
│   ├── style.css              # Custom glassmorphic stylesheet
│   └── app.js                 # Event listeners, chat logic, and log streaming
├── tests/                     # Unit test suites for primary modules
├── Dockerfile                 # Multi-stage optimized Docker deployment specification
├── pyproject.toml             # Modern packaging and tool configuration
├── render.yaml                # Deploy specification for cloud hosting
├── requirements.txt           # Consolidated API dependencies
├── supabase_schema.sql        # Database initialization schema
└── .env.example               # Template environment configuration
```

---

## Prerequisites

*   Python 3.10 or higher
*   Google Cloud Platform project with the **Google Calendar API** enabled
*   Google Calendar OAuth 2.0 Credentials
*   Supabase Account and Database URL
*   Google Gemini API Key

---

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/rajeev0521/project-AVA.git
cd project-AVA
```

### 2. Configure Environment Variables
Create a `.env` file at the root of the repository by copying the example:
```bash
cp .env.example .env
```
Fill in the details inside the `.env` file:
*   `GEMINI_API_KEY`: Your Gemini API access key.
*   `GOOGLE_APPLICATION_CREDENTIALS`: Path to your Google service account credentials file (e.g., `service_account.json`).
*   `SUPABASE_URL` & `SUPABASE_KEY`: Database endpoint details.
*   `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: OAuth keys for multi-user web dashboard authentication.

### 3. Initialize Database
Execute the SQL commands in `supabase_schema.sql` inside your Supabase SQL editor to create the required relational structures and table indexes.

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Running the Application

### 1. Backend REST Server
Run the FastAPI gateway service locally using Uvicorn:
```bash
uvicorn ava.api:app --host 127.0.0.1 --port 8000 --reload
```
Access the interactive API documentation at `http://127.0.0.1:8000/docs`.

### 2. Desktop Vocal Loop
To run AVA in local desktop voice mode with hotword detection and real-time mic tracking:
```bash
python -m ava.main
```
Speak the wake word **"Hey AVA"** to prompt the assistant.

### 3. Web Dashboard
Serve the `frontend/` directory using any local web server (e.g., Live Server, Nginx, or Python's HTTP module):
```bash
python -m http.server 3000
```
Open `http://localhost:3000` in your browser to interact with the glassmorphic console.

---

## Docker Deployment

Build the container image using the optimized Dockerfile:
```bash
docker build -t ava-assistant .
```

Run the container instance locally:
```bash
docker run -d -p 8000:8000 --env-file .env ava-assistant
```

---

## Contributing

We welcome all community contributions.
*   To report bugs or security issues, please open an Issue.
*   For codebase enhancements, please fork the repository and submit a Pull Request.

---

## License

This project is licensed under the MIT License. Refer to the LICENSE file for details.
