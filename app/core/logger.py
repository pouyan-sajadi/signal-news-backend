import logging
import os

logger = logging.getLogger("news-app")

if not logger.hasHandlers():
    # Determine log level from environment variable, default to INFO for development
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    # Map string level to logging module's level constants
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # For production, default to WARNING if LOG_LEVEL is not explicitly set
    if os.environ.get("RENDER") == "true" and log_level_str == "INFO": # Assuming RENDER env var is set on Render
        log_level = logging.WARNING

    logger.setLevel(log_level)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Console (StreamHandler for stdout/stderr)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Remove file handler for production environments
    # file_handler = logging.FileHandler("app.log")
    # file_handler.setFormatter(formatter)
    # logger.addHandler(file_handler)
