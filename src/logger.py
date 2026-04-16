"""Logging configuration for the GoodWe2MQTT daemon."""

import logging
import logging.handlers
from typing import Any, Dict
import os

# Get the root logger
log = logging.getLogger()

def setup_logging(config: Dict[str, Any]) -> None:
    """Sets up logging based on the provided configuration dictionary.

    Args:
        config: A dictionary containing logging configuration parameters.
    """
    log_level = config['logger']['log_level']
    log_to_file = bool(config['logger']['log_to_file'])
    log_file = config['logger']['log_file']
    log_to_console = bool(config['logger']['log_to_console'])
    log_rotate = bool(config['logger']['log_rotate'])
    log_rotate_size = int(config['logger']['log_rotate_size'])
    log_rotate_count = config['logger']['log_rotate_count']

    if log_level == 'DEBUG':
        log.setLevel(logging.DEBUG)
    elif log_level == 'INFO':
        log.setLevel(logging.INFO)
    elif log_level == 'WARNING':
        log.setLevel(logging.WARNING)
    elif log_level == 'ERROR':
        log.setLevel(logging.ERROR)
    elif log_level == 'CRITICAL':
        log.setLevel(logging.CRITICAL)
    else:
        log.setLevel(logging.INFO)  # default to INFO if log_level is not recognized

    # Clear existing handlers to prevent duplicate logging if called multiple times
    if log.hasHandlers():
        log.handlers.clear()

    if log_to_file:
        import os
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except Exception as e:
                print(f'Error creating log directory "{log_dir}": {e}')
        
        file_handler: logging.FileHandler
        if log_rotate:
            # Create a RotatingFileHandler object that rotates log files when they reach specified size.
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=log_rotate_size, backupCount=log_rotate_count
            )
        else:
            # Add a handler to the log object that writes messages to a file.
            file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
        log.addHandler(file_handler)

    if log_to_console:
        # Add a handler to the log object that prints messages to the console.
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(stream_handler)

config_file = ".env"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _load_logger_config() -> Dict[str, Any]:
    return {
        "logger": {
            "log_file": os.environ.get("G2M_LOG_FILE", "goodwe2mqtt.log"),
            "log_level": os.environ.get("G2M_LOG_LEVEL", "DEBUG"),
            "log_to_console": _env_bool("G2M_LOG_TO_CONSOLE", True),
            "log_to_file": _env_bool("G2M_LOG_TO_FILE", True),
            "log_rotate": _env_bool("G2M_LOG_ROTATE", True),
            "log_rotate_size": _env_int("G2M_LOG_ROTATE_SIZE", 1048576),
            "log_rotate_count": _env_int("G2M_LOG_ROTATE_COUNT", 5),
        }
    }

setup_logging(_load_logger_config())
