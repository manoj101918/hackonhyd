"""Structured (key=value) logging shared by the whole backend."""

import logging
import sys

_CONFIGURED = False


class KeyValueFormatter(logging.Formatter):
    """Renders `log.info("recall.done", extra={"kv": {...}})` as `event=recall.done hits=7 ...`."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        parts = [f"{ts} {record.levelname:<5} {record.name} event={record.getMessage()}"]
        for key, value in getattr(record, "kv", {}).items():
            text = str(value)
            if " " in text:
                text = '"' + text.replace('"', "'")[:300] + '"'
            parts.append(f"{key}={text}")
        if record.exc_info:
            parts.append("\n" + self.formatException(record.exc_info))
        return " ".join(parts)


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    root = logging.getLogger("dejavu")
    root.setLevel(level.upper())
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"dejavu.{name}")


def kv(**fields) -> dict:
    """Shorthand for the `extra=` argument: `log.info("event", extra=kv(a=1))`."""
    return {"kv": fields}
