from __future__ import annotations

import logging
from pathlib import Path


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "audio_salvage_hunter.log"


def configure_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not any(isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == str(LOG_FILE) for handler in root.handlers):
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)


def read_recent_logs(level: str = "", limit: int = 300) -> list[str]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    if level:
        needle = f" {level.upper()} "
        lines = [line for line in lines if needle in line]
    safe = []
    blocked = ("EBAY_CLIENT_SECRET", "EBAY_CLIENT_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "Authorization", "password", "token")
    for line in lines:
        if any(word.lower() in line.lower() for word in blocked):
            safe.append("[redacted sensitive log line]")
        else:
            safe.append(line)
    return safe
