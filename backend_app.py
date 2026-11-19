from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from app.core.process import process_news_backend, report_error
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

origins_str = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
origins = [origin.strip().rstrip('/') for origin in origins_str.split(",")]

logger.info(f"CORS allowed origins: {origins}")
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

REPORT_TIMEOUT_SECONDS = 15 * 60
REPORT_RETENTION_SECONDS = 60 * 60


@dataclass
class ReportJob:
    update: dict = field(default_factory=lambda: {"step": "search", "status": "running"})
    refined_topic: str | None = None
    websocket: WebSocket | None = None


# The service runs with one worker. Keep a job's latest update independent of its WebSocket.
report_jobs: dict[str, ReportJob] = {}
report_tasks: set[asyncio.Task] = set()


async def send_report_update(job: ReportJob, websocket: WebSocket):
    try:
        await asyncio.wait_for(websocket.send_json(job.update), timeout=2)
    except Exception:
        if job.websocket is websocket:
            job.websocket = None


async def run_report_job(job_id: str, job: ReportJob, request: NewsRequest):
    async def publish(update: dict):
        job.update = update
        if update.get("refined_topic"):
            job.refined_topic = update["refined_topic"]
        if job.websocket is not None:
            await send_report_update(job, job.websocket)

    try:
        await asyncio.wait_for(
            process_news_backend(request.topic, request.user_preferences, publish),
            timeout=REPORT_TIMEOUT_SECONDS,
        )
        if job.update["status"] != "error" and not (
            job.update["step"] == "editing" and job.update["status"] == "completed"
        ):
            await publish(report_error(job.update["step"]))
    except asyncio.TimeoutError:
        logger.warning("Report job %s timed out", job_id)
        await publish(report_error(job.update["step"], "timed_out"))
    except Exception:
        logger.exception("Report job %s failed", job_id)
        await publish(report_error(job.update["step"]))
    finally:
        asyncio.get_running_loop().call_later(REPORT_RETENTION_SECONDS, report_jobs.pop, job_id, None)


@app.post("/process_news")
async def process_news(request: NewsRequest):
    request.topic = request.topic.strip()
    if not request.topic:
        raise HTTPException(status_code=422, detail="Enter a topic to start a report.")
    job_id = str(uuid.uuid4())
    job = ReportJob()
    report_jobs[job_id] = job
    task = asyncio.create_task(run_report_job(job_id, job, request))
    report_tasks.add(task)
    task.add_done_callback(report_tasks.discard)
    return {"message": "Process started", "job_id": job_id}


@app.get("/report-jobs/{job_id}")
async def get_report_job(job_id: str, response: Response):
    headers = {"Cache-Control": "no-store"}
    job = report_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This report session has expired.", headers=headers)
    response.headers.update(headers)

    update = job.update
    status = update["status"]
    step = update["step"]
    if status == "error":
        return {"status": "error", "step": step, "code": update["code"]}
    if status == "completed" and step == "editing":
        return {"status": "completed", "step": step, "data": update["data"]}
    return {"status": "running", "step": step, "refined_topic": job.refined_topic}


@app.websocket("/ws/status/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    job = report_jobs.get(job_id)
    if job is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    job.websocket = websocket
    try:
        await send_report_update(job, websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for job_id: {job_id}")
    finally:
        if job.websocket is websocket:
            job.websocket = None

@app.get("/")
async def read_root():
    return {"message": "Backend is running"}

@app.post("/api/history")
async def save_search_history(request: Request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        jwt_token = auth_header.split(' ')[1]
        
        user_response = supabase.auth.get_user(jwt_token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        body = await request.json()
        search_topic = body.get('search_topic')
        report_summary = body.get('report_summary')

        if not search_topic or not report_summary:
            raise HTTPException(status_code=400, detail="Missing topic or summary")

        logger.info(f"Attempting to insert search history for user {user.id}")
        
        # Impersonate the user to enforce RLS policies for the insert
        supabase.postgrest.auth(jwt_token)
        insert_response = supabase.table("user_report_history").insert([
            {
                "user_id": user.id, # The RLS policy will double-check this
                "search_topic": search_topic,
                "report_summary": report_summary,
            },
        ]).execute()

        if insert_response.data:
            logger.info(f"Successfully saved search history for user {user.id}.")
            return {"success": True, "data": insert_response.data}
        else:
            logger.error(f"Failed to save search history for user {user.id}. Response: {insert_response}")
            raise HTTPException(status_code=500, detail="Failed to save search history.")

    except HTTPException as http_exc:
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

        # Impersonate the user to enforce RLS for the select
        supabase.postgrest.auth(jwt_token)
        response = supabase.table('user_report_history').select('*').order('created_at', desc=True).execute()

        if response.data:
            history_list = [record['report_summary'] for record in response.data]
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
    try:
        # Explicitly reset auth to the service_role key to avoid using a stale user JWT
        supabase.postgrest.auth(supabase_key)

        # RLS policy on tech_pulses table allows public read access.
        response = supabase.table('tech_pulses').select('pulse_data, created_at').order('created_at', desc=True).limit(1).single().execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="No tech pulse data found.")

        pulse_data = response.data.get('pulse_data')
        if isinstance(pulse_data, str):
            response.data['pulse_data'] = json.loads(pulse_data)

        return response.data

    except Exception as e:
        logger.exception(f"Error fetching or parsing latest tech pulse: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing tech pulse data: {str(e)}")

@app.get("/reports/{job_id}")
async def get_report(job_id: str, request: Request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        jwt_token = auth_header.split(' ')[1]

        # Impersonate the user to enforce RLS
        supabase.postgrest.auth(jwt_token)
        response = supabase.table('user_report_history')\
            .select('*')\
            .eq('report_summary->>job_id', job_id)\
            .limit(1)\
            .execute()

        if response.data:
            return response.data[0]['report_summary']
        else:
            raise HTTPException(status_code=404, detail="Report not found or not authorized")

    except HTTPException as http_exc:
        raise http_exc
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

        # Impersonate the user to enforce RLS for the delete
        supabase.postgrest.auth(jwt_token)
        delete_response = supabase.table("user_report_history")\
            .delete()\
            .eq('report_summary->>job_id', job_id)\
            .execute()

        if delete_response.data:
            return {"success": True, "message": "Report deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Report not found or unauthorized.")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception(f"Error deleting search history: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")
