# 🗓️ AVA – Voice-Based AI Calendar Assistant

**AVA** is a voice-activated AI assistant that helps you manage your Google Calendar using natural language. Designed for seamless interaction, AVA lets you schedule events, set reminders, and check your calendar – all hands-free.

---

## ✨ Features

* 🗣️ Wake word detection: `"Hey AVA"`
* 🧠 Natural Language Processing (NLP) for calendar tasks
* 📅 Google Calendar API integration
* 🔊 Real-time voice recognition
* 🔐 Google OAuth 2.0 authentication
* 🐳 Dockerized for easy deployment
* 🤖 Gemini API for intelligent language understanding

---

## 🛠️ Prerequisites

* Python 3.10(recommended)
* Google Cloud Platform account
* Google Calendar API enabled
* Gemini API
* Docker (optional, for containerization)

---

## 🚀 Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/ava-assistant.git
cd ava-assistant
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Google Cloud Setup

* Create a project in **Google Cloud Console**
* Enable the **Google Calendar API**
* Set up **OAuth 2.0 Client ID** credentials
* Download the credentials file and save it as:

```bash
credentials.json
```

### 4. Gemini API Setup

* Create an account at [Gemini API](https://ai.google.dev/)
* Generate your API key

### 5. Create `.env` Configuration File

```env
GOOGLE_APPLICATION_CREDENTIALS=credentials.json
GEMINI_API_KEY=your_gemini_api_key
PORCUPINE_ACCESS_KEY=your_porcupine_access_key
```

---

## ▶️ How to Use

1. Run the application:

```bash
python main.py
```

2. Say **"Hey AVA"** to activate the assistant

3. Give a command, such as:

* `"Schedule a meeting for tomorrow at 2 PM"`
* `"What's on my calendar for next week?"`
* `"Add a reminder for my birthday"`

---

## 📁 Project Structure

```
ava/
├── main.py              # Application entry point
├── voice_processor.py   # Handles wake word & voice input
├── calendar_manager.py  # Google Calendar event logic
├── nlp_processor.py     # NLP & command parsing (Gemini API)
├── auth_manager.py      # Google OAuth 2.0 authentication
└── Speech_manager.py    # Speech synthesis with Piper TTS
```

---

## 🐳 Docker Deployment

1. Build the Docker image:

```bash
docker build -t ava-assistant .
```

2. Run the container:

```bash
docker run -it ava-assistant
```

---

## 🤝 Contributing

We welcome all contributions!

* Found a bug? Open an [issue](https://github.com/yourusername/ava-assistant/issues)
* Want to add a feature? Submit a [pull request](https://github.com/yourusername/ava-assistant/pulls)

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

## Speech Output with Piper TTS

The `ava/Speech_manager.py` module enables AVA to speak responses aloud using neural text-to-speech (TTS).

### How it works
- Uses [Piper TTS](https://github.com/rhasspy/piper) for fast, high-quality, offline speech synthesis.
- By default, it looks for a Piper voice model file (e.g., `en_US-amy-low.onnx`) in the project directory.
- When AVA generates a response, `Speech_manager.py` synthesizes the text and plays the audio automatically.

### Setup Instructions
1. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```
2. **Download a Piper voice model**
   - Visit the [Piper voices repository](https://github.com/rhasspy/piper-voices).
   - Download a suitable `.onnx` model (e.g., `en_US-amy-low.onnx` for an English female voice).
   - Place the model file in your project directory.
   - By default, `Speech_manager.py` expects the file to be named `en_US-amy-low.onnx`. You can change the filename in the code if you use a different model.

3. **Run AVA**
   - AVA will now speak all responses aloud using the selected Piper TTS voice.

### Troubleshooting
- If you see an error about the Piper model not being found, make sure you have downloaded the `.onnx` file and placed it in the correct location.
- If you have audio playback issues, ensure your system audio is working and the `sounddevice` package is installed.
