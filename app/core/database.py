from pymongo import MongoClient
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import os
from app.core.logger import logger

class ReportPreferences(BaseModel):
    focus: str
    depth: int
    tone: str

class AgentDetails(BaseModel):
    search: List[dict] = []
    profiling: List[dict] = []
    selection: List[dict] = []
    synthesis: str = ""
    editing: str = ""

class Report(BaseModel):
    job_id: str = Field(...)
    topic: str = Field(...)
    user_preferences: ReportPreferences
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    final_report_data: AgentDetails

class Database:
    client: Optional[MongoClient] = None
    db: Optional[any] = None

    def connect(self):
        MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        DB_NAME = os.getenv("DB_NAME", "signal_app_db")
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        logger.info(f"Connected to MongoDB: {MONGO_URI}, Database: {DB_NAME}")

    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed.")

db_client = Database()
