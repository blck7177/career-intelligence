"""
Structured JSON logging for career-openclaw.

Usage:
    from packages.infrastructure.observability.logging import configure_logging

    configure_logging()  # call once at app / worker startup

After calling configure_logging(), every logger.info/warning/error call emits
a JSON line to stdout with:
  - timestamp (ISO-8601, UTC)
  - level
  - logger name
  - message
  - correlation_id (if set via set_correlation_id())
  - any extra keyword args passed to the log call

Design:
  - Structured logging is used for correlation across API → Redis → Worker → DB
  - correlation_id ties an API request to all downstream task/agent events
  - Log lines are newline-delimited JSON (NDJSON), easy to forward to any log sink
  - Does NOT depend on FastAPI, Redis, SQLAlchemy, Celery, or OpenAI
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Thread/task-local correlation_id for tracing a request across services.
# Set by API middleware; propagated to Celery tasks via task headers.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(cid: str | None) -> None:
    """Set the correlation_id for the current context (request / task)."""
    _correlation_id.set(cid)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """
    Emits one JSON object per log record to stdout (NDJSON).

    Extra fields can be attached to any log call:
        logger.info("msg", extra={"run_id": "run_abc", "task_id": "task_xyz"})
    """

    _RESERVED = {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs",
        "msg", "name", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "thread", "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        cid = get_correlation_id()
        if cid:
            entry["correlation_id"] = cid

        # Include extra fields passed via extra={...}
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                entry[key] = value

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            entry["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(entry, default=str)


# ---------------------------------------------------------------------------
# Configuration entrypoint
# ---------------------------------------------------------------------------


def configure_logging(
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """
    Configure root logger.

    Args:
        level: log level string (DEBUG/INFO/WARNING/ERROR). Defaults to LOG_LEVEL env var or INFO.
        json_output: emit JSON lines. Defaults to JSON_LOGGING env var or True in production.
    """
    resolved_level = level or os.environ.get("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    # JSON output is default; disable in interactive dev if LOG_JSON=0
    if json_output is None:
        json_output = os.environ.get("LOG_JSON", "1") not in {"0", "false", "False"}

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any existing handlers (e.g. uvicorn/celery may install theirs)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
        )

    root.addHandler(handler)

    # Suppress noisy third-party loggers unless at WARNING+
    _quiet = [
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "celery.app.trace",
        "celery.worker.strategy",
        "urllib3.connectionpool",
        "httpx",
        "httpcore",
    ]
    for name in _quiet:
        logging.getLogger(name).setLevel(logging.WARNING)
