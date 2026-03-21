# 🗓️ AVA – Voice-Based AI Calendar Assistant

**AVA** is a voice-activated AI assistant that helps you manage your Google Calendar using natural language. Designed for seamless interaction, AVA lets you schedule events, set reminders, and check your calendar – all hands-free.

---

## ✨ Features

* 🗣️ Custom Wake Word ("Hey AVA") using OpenWakeWord (100% offline, zero latency)
* 🧠 LangChain NLP processing using Gemini 1.5 Pro
* 📅 Google Calendar API integration
* 🔊 Real-time voice recognition via Whisper
* 🔐 Google Service Account (JWT) authentication for zero token expiry
* 🐳 Dockerized for easy deployment

---

## 🛠️ Prerequisites

* Python 3.10 (recommended)
* Google Cloud Platform account with **Service Account** credentials
* Google Calendar API enabled
* Gemini API Key

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

### 3. Google Cloud Setup (Service Account)

* Create a project in **Google Cloud Console**
* Enable the **Google Calendar API**
* Create a **Service Account** and generate a JSON Key.
* Download the key and save it in the project root as:

  ```bash
  service_account.json
  ```
* **IMPORTANT:** Share your Google Calendar with the Service Account email and grant it "Make changes to events" permission.

### 4. Wake Word & Gemini Configuration

* Create an account at [Google AI Studio](https://aistudio.google.com/) for your Gemini API key.
* **Train your wake word**: Read [how_to_train_hey_ava.md](how_to_train_hey_ava.md) to generate your custom `hey_ava.onnx` OpenWakeWord model and place it in the `ava/` folder.

### 5. Create `.env` Configuration File

```env
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
GEMINI_API_KEY=your_gemini_api_key
WAKE_WORD_MODEL=hey_ava.onnx
WAKE_WORD_THRESHOLD=0.5
AVA_USER_NAME=YourName
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

```text
ava/
├── main.py              # Application entry point
├── voice_processor.py   # Handles wake word (OpenWakeWord) & voice input
├── calendar_manager.py  # Google Calendar event logic
├── nlp_processor.py     # NLP & command parsing via LangChain
├── auth_manager.py      # Google Service Account JWT auth
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
