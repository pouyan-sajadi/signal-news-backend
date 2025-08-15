import os
from dotenv import load_dotenv
from app.core.logger import logger
# Always try to load .env for local development
try:
    load_dotenv()
except Exception as e:
    logger.debug(f"Could not load .env: {e}")

def get_secret(key, default=None):
    """Get secret from environment variables."""
    env_value = os.getenv(key, default)
    if env_value:
        logger.debug(f"Got {key} from environment")
    else:
        logger.error(f"❌ {key} not found in environment")
    return env_value

# Load configuration
SERPAPI_KEY = get_secret("SERPAPI_API_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
MODEL = "gpt-5-mini"
NUM_SOURCES = 15