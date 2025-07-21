from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uuid
import asyncio
from app.core.process import process_news_backend
from app.core.logger import logger

app = FastAPI()

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
    asyncio.create_task(process_news_backend(request.topic, request.user_preferences, get_websocket_sender(job_id)))
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


def get_websocket_sender(job_id: str):
    async def sender(data: dict):
        if job_id in connections and connections[job_id]:
            await connections[job_id].send_json(data)
    return sender
