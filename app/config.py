import os
from dotenv import load_dotenv
from app.core.logger import logger
from app.core.database import db_client

# Always try to load .env for local development
try:
    load_dotenv()
except Exception as e:
    logger.info(f"Could not load .env: {e}")

def get_secret(key, default=None):
    """Get secret from environment variables."""
    env_value = os.getenv(key, default)
    if env_value:
        logger.info(f"Got {key} from environment")
    else:
        logger.info(f"❌ {key} not found in environment")
    return env_value

# Load configuration
SERPAPI_KEY = get_secret("SERPAPI_API_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
#MODEL = "gpt-4o-mini"
MODEL = "gpt-4.1-mini-2025-04-14"
NUM_SOURCES = 10

def connect_db():
    db_client.connect()

def close_db():
    db_client.close()