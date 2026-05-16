# test

from loguru import logger
import sys
import json
from datetime import datetime
import inspect


def _json_log_sink(message):
    record = message.record
    frame = record["frame"]
    log_entry = {
        "severity": record["level"].name,
        "message": record["message"],
        "function": frame.f_code.co_name,
        "line": frame.f_lineno,
        "time": record["time"].isoformat(),
    }
    sys.stdout.write(json.dumps(log_entry) + "\n")


logger.remove()
logger.add(_json_log_sink, level="INFO", backtrace=True, diagnose=False)


def pull_main_handler():
    print("test")  # Added as per your request
    logger.info("pull handler started")
    # existing pull logic goes here