from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import asyncio
from datetime import datetime
from app.core.process import process_news_backend
from app.core.logger import logger
import uvicorn
import json
from typing import List, Dict, Any
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Supabase Setup ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
# --------------------

app = FastAPI()

from app.core.database import db_client, Report # Import db_client

@app.on_event("startup")
async def startup_event():
    db_client.connect()
    logger.info("Database connection established.")

@app.on_event("shutdown")
async def shutdown_event():
    db_client.close()
    logger.info("Database connection closed.")

origins_str = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
origins = [origin.strip() for origin in origins_str.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

class NewsRequest(BaseModel):
    topic: str
    user_preferences: dict

connections = {}

@app.post("/process_news")
async def process_news(request: NewsRequest):
    logger.info(f"Received request for topic: {request.topic}")
    job_id = str(uuid.uuid4())
    connections[job_id] = None
    logger.info(f"Created job_id: {job_id}")
    asyncio.create_task(process_news_backend(job_id, request.topic, request.user_preferences, get_websocket_sender(job_id)))
    return {"message": "Process started", "job_id": job_id}

@app.websocket("/ws/status/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    connections[job_id] = websocket
    logger.info(f"WebSocket connection established for job_id: {job_id}")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for job_id: {job_id}")
        del connections[job_id]

@app.get("/")
async def read_root():
    return {"message": "Backend is running"}

@app.post("/api/history")
async def save_search_history(request: Request):
    try:
        # 1. Authenticate the user by getting the session from the Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        jwt_token = auth_header.split(' ')[1]
        
        # Verify the token with Supabase
        try:
            user_response = supabase.auth.get_user(jwt_token)
            user = user_response.user
            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Supabase token verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

        # 2. Parse the request body
        body = await request.json()
        search_topic = body.get('search_topic')
        report_summary = body.get('report_summary')

        if not search_topic or not report_summary:
            raise HTTPException(status_code=400, detail="Missing topic or summary")

        # 3. Insert the data into the database
        logger.info(f"Attempting to insert search history for user {user.id} with topic '{search_topic}'")
        insert_response = supabase.table("user_report_history").insert([
            {
                "user_id": user.id,
                "search_topic": search_topic,
                "report_summary": report_summary,
            },
        ]).execute()

        # Log the full response from Supabase for debugging
        logger.info(f"Supabase insert response: {insert_response}")

        if insert_response.data:
            logger.info(f"Successfully saved search history for user {user.id}.")
            return {"success": True, "data": insert_response.data}
        else:
            # Supabase Python client v1 does not raise exceptions on DB errors in the same way as v2.
            # We check for the absence of data as an indicator of a potential issue.
            logger.error(f"Failed to save search history for user {user.id}. Response: {insert_response}")
            raise HTTPException(status_code=500, detail="Failed to save search history.")

    except HTTPException as http_exc:
        # Re-raise HTTPException to let FastAPI handle it
        raise http_exc
    except Exception as e:
        logger.exception(f"Error saving search history: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get("/api/history")
async def get_search_history(request: Request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        jwt_token = auth_header.split(' ')[1]
        
        try:
            user_response = supabase.auth.get_user(jwt_token)
            user = user_response.user
            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Supabase token verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

        response = supabase.table('user_report_history').select('*').eq('user_id', user.id).order('created_at', desc=True).execute()

        if response.data:
            # Extract the 'report_summary' object from each record
            history_list = [record['report_summary'] for record in response.data]
            # Log the timestamp of the first item if history exists
            if history_list:
                logger.info(f"Backend sending history. First item timestamp: {history_list[0].get('timestamp')}")
            return history_list
        else:
            return []

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception(f"Error fetching search history: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get("/api/tech-pulse/latest")
async def get_latest_tech_pulse():
    """
    Fetches the most recent 'tech_pulse' data from the Supabase database.
    """
    try:
        response = supabase.table('tech_pulses').select('pulse_data, created_at').order('created_at', desc=True).limit(1).single().execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="No tech pulse data found.")

        # The pulse_data might be a string or already a dict. Handle both cases.
        pulse_data = response.data.get('pulse_data')
        if isinstance(pulse_data, str):
            response.data['pulse_data'] = json.loads(pulse_data)

        return response.data

    except Exception as e:
        logger.exception(f"Error fetching or parsing latest tech pulse: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing tech pulse data: {str(e)}")
# -----------------------------------------


@app.get("/reports/{job_id}")
async def get_report(job_id: str):
    """
    Fetches a single report from the user_report_history table by its job_id
    stored within the report_summary JSONB column.
    """
    try:
        logger.info(f"Fetching report with job_id: {job_id}")
        
        # Query inside the JSONB column `report_summary` for the matching job_id
        response = supabase.table('user_report_history').select('*').eq('report_summary->>job_id', job_id).limit(1).execute()
        
        logger.info(f"Supabase response for job_id {job_id}: {response}")

        if response.data:
            logger.info(f"Successfully fetched report for job_id: {job_id}")
            # Extract the report_summary JSON object and return it
            return response.data[0]['report_summary']
        else:
            logger.warning(f"Report with job_id {job_id} not found.")
            raise HTTPException(status_code=404, detail="Report not found")

    except Exception as e:
        logger.exception(f"An error occurred while fetching report {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


@app.delete("/api/history/{job_id}")
async def delete_search_history(job_id: str, request: Request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        jwt_token = auth_header.split(' ')[1]
        
        try:
            user_response = supabase.auth.get_user(jwt_token)
            user = user_response.user
            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Supabase token verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

        # Delete the record where user_id matches and job_id is found within report_summary
        delete_response = supabase.table("user_report_history").delete().eq('user_id', user.id).eq('report_summary->>job_id', job_id).execute()

        if delete_response.data:
            logger.info(f"Successfully deleted report {job_id} for user {user.id}.")
            return {"success": True, "message": "Report deleted successfully"}
        else:
            logger.warning(f"Report {job_id} not found or not authorized for user {user.id}.")
            raise HTTPException(status_code=404, detail="Report not found or unauthorized.")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception(f"Error deleting search history: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")


def get_websocket_sender(job_id: str):
    async def sender(data: dict):
        if job_id in connections and connections[job_id]:
            try:
                await connections[job_id].send_json(data)
            except Exception as e:
                logger.error(f"Error sending websocket message for job_id {job_id}: {e}")
    return sender

# This block is removed for Gunicorn deployment on Railway.
# The application will be run using a Procfile and Gunicorn.
# if __name__ == "__main__":
#     # --- Diagnostic: Print all registered Routes ---
#     logger.info("--- Registered Routes ---")
#     for route in app.routes:
#         if hasattr(route, "methods"):
#             logger.info(f"Path: {route.path}, Methods: {list(route.methods)}")
#     logger.info("-------------------------")
#     # ---------------------------------------------
#     uvicorn.run(app, host="0.0.0.0", port=8000)