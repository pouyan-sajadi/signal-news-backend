# Signal App Backend (FastAPI)

This directory contains the FastAPI backend for the Signal news processing application. It is responsible for handling news processing workflows, communicating with external APIs (SerpAPI, OpenAI), and providing real-time updates to the frontend via WebSockets.

## Features

*   **HTTP API:** Exposes a `/process_news` endpoint to initiate news processing.
*   **WebSocket API:** Provides a `/ws/status/{job_id}` endpoint for real-time status updates and final report delivery.
*   **Agent-based Processing:** Utilizes AI agents for search query refinement, source profiling, diversity selection, debate synthesis, and creative editing.
*   **Secret Management:** Securely loads API keys from environment variables (supports `.env` for local development).

## Setup and Installation

1.  **Navigate to the backend directory:**
    ```bash
    cd signal-app-backend
    ```

2.  **Create and activate a Python virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure API Keys:**
    Create a `.env` file in the `signal-app-backend` directory (the same directory as `backend_app.py`) and add your API keys:
    ```
    OPENAI_API_KEY="your_openai_api_key_here"
    SERPAPI_KEY="your_serpapi_key_here"
    ```
    **Important:** Replace `"your_openai_api_key_here"` and `"your_serpapi_key_here"` with your actual API keys. Do not commit this file to version control.

## Running the Backend

To start the FastAPI server:

```bash
# Make sure you are in the signal-app-backend directory
cd signal-app-backend
# Activate your virtual environment if not already active
source venv/bin/activate
# Run the Uvicorn server in the background
./venv/bin/uvicorn backend_app:app --host 0.0.0.0 --port 8000 &
```

The backend will run on `http://127.0.0.1:8000`.

## Project Structure

*   `backend_app.py`: Main FastAPI application, defines API and WebSocket endpoints.
*   `app/`: Contains the core logic of the application.
    *   `app/__init__.py`: Initializes the `app` package.
    *   `app/config.py`: Configuration settings, including secret loading.
    *   `app/agents/`: AI agent definitions and related logic.
    *   `app/core/`: Core processing modules.
        *   `process.py`: Orchestrates the news processing workflow.
        *   `logger.py`: Configures logging for the application.
        *   `utils.py`: Utility functions (e.g., news searching).
*   `requirements.txt`: Python dependencies for the backend.
*   `venv/`: Python virtual environment.
