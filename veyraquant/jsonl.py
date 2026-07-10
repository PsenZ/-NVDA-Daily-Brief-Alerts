import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


def read_entries(path: str) -> list[dict[str, Any]]:
    """Read a JSON-lines file into a list of dicts. Missing/unreadable -> []."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        logger.warning("Failed to read JSONL file: %s", path, exc_info=True)
        return []


def write_entries(path: str, entries: list[dict[str, Any]]) -> None:
    """Write entries as JSON-lines, creating the parent directory if needed."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
