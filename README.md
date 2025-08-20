# Signal App Backend (FastAPI)

This directory contains the FastAPI backend for the Signal news processing application. It is responsible for handling news processing workflows, communicating with external APIs (SerpAPI, OpenAI), providing real-time updates to the frontend via WebSockets, and managing user data via Supabase.

## Features

*   **News Processing Engine:**
    *   **HTTP API:** Exposes a `/process_news` endpoint to initiate news processing with a given topic and user preferences.
    *   **WebSocket API:** Provides a `/ws/status/{job_id}` endpoint for real-time status updates and final report delivery.
    *   **Agent-based Processing:** Utilizes AI agents for search query refinement, source profiling, diversity selection, debate synthesis, and creative editing.
*   **User and Report Data Management:**
    *   **Authentication:** Manages user authentication using Supabase.
    *   **Persistent Report History:** Integrates with Supabase to store and retrieve user-specific generated reports.
    *   **History API:** Provides endpoints to get, save, and delete user report history (`/api/history`).
    *   **Report Retrieval:** Allows fetching a single report by its job ID (`/reports/{job_id}`).
*   **Dashboard Data:**
    *   **Daily News Dashboard API:** Exposes a `/api/tech-pulse/latest` endpoint to fetch aggregated data for the daily news dashboard.
*   **Secret Management:** Securely loads API keys and database URLs from environment variables (supports `.env` for local development).

## Security: Defense in Depth with RLS

This backend implements a robust "defense in depth" security model using Supabase's Row Level Security (RLS).

*   **RLS Policies:** All tables containing user-specific data (e.g., `user_report_history`) are protected by RLS policies. These policies are the single source of truth for data access rules, ensuring at the database level that users can only read, write, and delete their own data.
*   **User Impersonation:** API endpoints that access user-specific data are designed to impersonate the end-user. The user's JWT is forwarded to the database with each request, allowing the RLS policies to be correctly and securely enforced based on the user's identity (`auth.uid()`).

This approach ensures that even if there were a bug in the application logic, the database itself would prevent any unauthorized data access.

## API Endpoints

*   `POST /process_news`: Starts the news report generation process.
*   `WS /ws/status/{job_id}`: Real-time progress updates for a generation job.
*   `POST /api/history`: Saves a new report to the user's history (requires authentication).
*   `GET /api/history`: Retrieves the authenticated user's report history.
*   `DELETE /api/history/{job_id}`: Deletes a specific report from the user's history (requires authentication).
*   `GET /reports/{job_id}`: Retrieves a single, specific report by its job ID.
*   `GET /api/tech-pulse/latest`: Fetches the latest data for the "Tech Pulse" dashboard.

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

4.  **Set up Supabase:**
    This project uses Supabase for its database and authentication. You will need to have a Supabase project set up. The backend automatically handles table creation if they don't exist.

5.  **Configure API Keys and Environment Variables:**
    Create a `.env` file in the `signal-app-backend` directory and add the following:
    ```
    OPENAI_API_KEY="your_openai_api_key_here"
    SERPAPI_KEY="your_serpapi_key_here"
    SUPABASE_URL="your_supabase_project_url"
    SUPABASE_SERVICE_ROLE_KEY="your_supabase_service_role_key"
    ```

## Running the Backend

To start the FastAPI server:

```bash
# Make sure you are in the signal-app-backend directory
cd signal-app-backend
# Activate your virtual environment if not already active
source venv/bin/activate
# Run the Uvicorn server
uvicorn backend_app:app --host 0.0.0.0 --port 8000 --reload
```

The backend will run on `http://127.0.0.1:8000`. The `--reload` flag is recommended for development to automatically apply code changes.

## Project Structure

*   `backend_app.py`: Main FastAPI application file. Defines all API and WebSocket endpoints, and handles Supabase integration.
*   `app/`: Contains the core logic of the application.
    *   `__init__.py`: Initializes the `app` package.
    *   `config.py`: Configuration settings, including secret loading.
    *   `agents/`: Contains the definitions and logic for the various AI agents used in the processing pipeline (e.g., search, profiling, synthesis).
    *   `core/`: Contains the core application modules.
        *   `process.py`: Orchestrates the main news processing workflow, coordinating the AI agents.
        *   `logger.py`: Configures application-wide logging.
        *   `utils.py`: Utility functions used across the application.
*   `requirements.txt`: A list of all Python dependencies required for the backend.
*   `.env`: (Locally created) File for storing environment variables securely.
*   `venv/`: (Locially created) Directory for the Python virtual environment.
