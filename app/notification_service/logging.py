import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key in ("request_id", "attempt", "error_category", "retry_delay", "state_saved"):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        return json.dumps(fields)


def configure_logging() -> None:
    logger = logging.getLogger("notification_service")
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
