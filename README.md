# AVA 2.0 - Generative AI Calendar Assistant

AVA 2.0 is an advanced, high-performance calendar assistant powered by Google's Gemini 2.0 Flash. Rebuilt from the ground up to replace legacy regex and local machine learning models, AVA 2.0 leverages generative AI for deep semantic reasoning, multi-turn conversation state tracking, and seamless Google Calendar management.

---

## Key Technical Features

### 1. Generative AI Core (Assistant Brain)
*   **Gemini 2.0 Flash Integration:** The core orchestration engine relies on Gemini 2.0 Flash to inherently understand intents, extract temporal entities, and formulate responses without manual rule-based parsing.
*   **Dynamic Tool Routing:** A modular `BaseTool` architecture dynamically exposes internal capabilities (e.g., Calendar CRUD, current time resolution) as structured JSON schemas to the Gemini function-calling API.

### 2. Conversational State Management
*   **Stateful Multi-Turn Context:** Integrates an in-memory `SessionManager` utilizing an LRU (Least Recently Used) cache and TTL (Time-To-Live) eviction policy.
*   **Missing Field Resolution:** Retains the `genai.ChatSession` across discrete REST or WebSocket requests, enabling the assistant to ask follow-up questions when a user provides incomplete calendar instructions.

### 3. Advanced NLP Temporal Parsing
*   **LLM-Driven Time Extraction:** The `NLTimeParser` delegates complex natural language date and time extraction to the LLM, returning precise, standardized ISO-8601 timestamps without fragile regex configurations.

### 4. Comprehensive Calendar Integrations
*   **Full CRUD Capabilities:** Modularized tools for creating, reading, updating, and deleting Google Calendar events directly through natural language instructions.

### 5. Dockerized Deployment
*   **Reproducible Ecosystem:** Fully containerized architecture using `docker-compose`, providing consistent local development environments and simplified cloud deployment.

---

## Technical Architecture

```text
project-AVA/
├── ava/
│   ├── api/                   # FastAPI service layer and API routes
│   ├── brain/                 # LLM Orchestrator and Tool Routing
│   │   ├── assistant_brain.py
│   │   └── tool_router.py
│   ├── calendar/              # Google Calendar OAuth and API integrations
│   ├── conversation/          # Session management and NLP parsers
│   │   ├── state_manager.py
│   │   └── time_parser.py
│   ├── tools/                 # Extensible tool plugins for the Brain
│   │   ├── base_tool.py
│   │   ├── calendar_tool.py
│   │   └── time_tool.py
│   ├── logger.py              # Structured, rotating file/console logging
│   ├── main.py                # Command-Line loop and entry point
│   └── rate_limiter.py        # Token-bucket API protection middleware
├── docker/
│   ├── Dockerfile             # Multi-stage optimized Docker deployment specification
│   └── docker-compose.yml     # Compose file for service orchestration
├── tests/                     # Automated unit and integration test suites
├── pyproject.toml             # Modern packaging and tool configuration
├── requirements.txt           # Consolidated API dependencies
└── .env.example               # Template environment configuration
```

---

## Prerequisites

*   **Docker and Docker Compose:** Required for running the containerized application.
*   **Google Gemini API Key:** Required for the Generative AI orchestration.
*   **Google Cloud Platform Project:** Must have the Google Calendar API enabled with OAuth 2.0 Credentials.
*   **Supabase Account:** Required for extended database state and memory persistence.

---

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/rajeev0521/project-AVA.git
cd project-AVA
```

### 2. Configure Environment Variables
Create a `.env` file at the root of the repository by copying the template:
```bash
cp .env.example .env
```
Fill in the details inside the `.env` file:
*   `GEMINI_API_KEY`: Your Gemini API access key.
*   `GOOGLE_APPLICATION_CREDENTIALS`: Path to your Google service account credentials file.
*   `SUPABASE_URL` & `SUPABASE_KEY`: Database endpoint details.
*   `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: OAuth keys for multi-user web dashboard authentication.

### 3. Install Dependencies (Local Development)
If you prefer running tests or running the application outside of Docker:
```bash
pip install -r requirements.txt
```

---

## Running the Application

### 1. Docker Environment (Recommended)
Build and run the application stack using Docker Compose:
```bash
docker-compose -f docker/docker-compose.yml up --build
```
This will start the FastAPI backend and any associated services defined in the configuration. Access the interactive API documentation at `http://localhost:8000/docs`.

### 2. Running Automated Tests
To run the test suite within the Docker container:
```bash
docker-compose -f docker/docker-compose.yml run ava pytest tests/unit/
```

---

## Contributing

We welcome all community contributions.
*   To report bugs or security issues, please open an Issue.
*   For codebase enhancements, please fork the repository and submit a Pull Request.

---

## License

This project is licensed under the MIT License. Refer to the LICENSE file for details.
