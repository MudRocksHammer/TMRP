import json
import logging
from datetime import datetime, timezone

from myproj.config import AppConfig


def configure_logging(config: AppConfig) -> logging.Logger:
    logger = logging.getLogger("myproj")
    logger.setLevel(config.log_level)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    logger.propagate = False

    return logger


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
        }
        return json.dumps(log_record, ensure_ascii=False)
