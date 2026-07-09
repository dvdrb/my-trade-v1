from __future__ import annotations

import re
import sys
from pathlib import Path

from loguru import logger


SECRET_PATTERNS = [
    re.compile(r"(HL_SECRET_KEY=)[^\s]+", re.IGNORECASE),
    re.compile(r"(secret(?:_key)?['\"]?\s*[:=]\s*['\"]?)[^'\"\s,]+", re.IGNORECASE),
    re.compile(r"(token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,]+", re.IGNORECASE),
]


def _redact(message: str) -> str:
    redacted = message
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def setup_logger(log_path: str | Path = "logs/bot.log") -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", filter=lambda r: _filter(r))
    logger.add(log_path, level="INFO", rotation="5 MB", retention=5, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", filter=lambda r: _filter(r))


def _filter(record: dict) -> bool:
    record["message"] = _redact(record["message"])
    return True
