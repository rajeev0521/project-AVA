"""
Centralized logging configuration for AVA.
Usage: from logger import get_logger
       logger = get_logger(__name__)
"""

import logging
import sys
from pathlib import Path


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Create and return a configured logger instance.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
        level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured logging.Logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Console handler with colored formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    # Format: [2026-05-29 12:30:00] [INFO] [module_name] Message
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    import json
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_record = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                log_record["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_record)

    # File handler for persistent logs
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    file_handler = logging.FileHandler(log_dir / "ava.json.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)
    
    return logger

