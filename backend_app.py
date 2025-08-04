from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import asyncio
from datetime import datetime
from app.core.process import process_news_backend
from app.core.logger import logger
from app.config import connect_db, close_db
import uvicorn
from app.core.database import db_client
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

@app.on_event("startup")
async def startup_event():
    connect_db()

@app.on_event("shutdown")
async def shutdown_event():
    close_db()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.get("/reports/history", response_model=List[Dict[str, Any]])
async def get_report_history():
    """Fetch a list of all saved reports, returning only essential fields."""
    try:
        # Fetch reports, excluding the _id and final_report_data for a lighter response
        reports_cursor = db_client.db["reports"].find({}, {"_id": 0, "job_id": 1, "topic": 1, "timestamp": 1, "user_preferences": 1})
        history = []
        for report in await asyncio.to_thread(list, reports_cursor):
            # Ensure timestamp is formatted as ISO 8601 with Z for UTC
            if 'timestamp' in report and isinstance(report['timestamp'], datetime):
                report['timestamp'] = report['timestamp'].isoformat(timespec='microseconds') + 'Z'
            history.append(report)
        logger.info(f"Fetched {len(history)} reports from history.")
        return history
    except Exception as e:
        logger.exception("Error fetching report history")
        raise HTTPException(status_code=500, detail=f"Failed to fetch report history: {e}")

@app.get("/reports/{job_id}", response_model=Dict[str, Any])
async def get_single_report(job_id: str):
    """Fetch a single report by its job_id."""
    try:
        report = await asyncio.to_thread(db_client.db["reports"].find_one, {"job_id": job_id}, {"_id": 0})
        if report:
            logger.info(f"Fetched report with job_id: {job_id}")
            return report
        else:
            logger.warning(f"Report with job_id {job_id} not found.")
            raise HTTPException(status_code=404, detail="Report not found")
    except Exception as e:
        logger.exception(f"Error fetching report {job_id}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch report: {e}")

import json

# ... (keep existing imports)

import json

# ... (other imports)

# --- New Endpoint for Daily News Dashboard ---
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

def get_websocket_sender(job_id: str):
    async def sender(data: dict):
        if job_id in connections and connections[job_id]:
            try:
                await connections[job_id].send_json(data)
            except Exception as e:
                logger.error(f"Error sending websocket message for job_id {job_id}: {e}")
    return sender

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
