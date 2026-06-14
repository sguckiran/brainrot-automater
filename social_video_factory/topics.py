"""Topic rotation for the unattended autopilot loop.

WHY deterministic config rotation (not LLM-generated ideas): an unattended
poster should be predictable and controllable. The user lists the topics and
templates they want in Hermes ``config.yaml``; this module hands them out one at
a time, advancing a persisted cursor so successive runs don't keep producing the
SAME topic. (Per-job creative variation still happens downstream in
``ideas.py`` / ``script.py``.)

If no topics are configured, ``next_topics`` returns an empty list — so a fresh
install never posts anything until the user opts in.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from social_video_factory import config

_CURSOR_FILENAME = "autopilot_cursor.json"


def _cursor_path() -> Path:
    return config.state_dir() / _CURSOR_FILENAME


def _read_cursor() -> int:
    try:
        with _cursor_path().open(encoding="utf-8") as fh:
            return int(json.load(fh).get("cursor", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def _write_cursor(cursor: int) -> None:
    path = _cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".cursor.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"cursor": cursor}, fh)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def next_topics(n: int) -> list[tuple[str, str]]:
    """Return up to ``n`` ``(template, topic)`` pairs, advancing the cursor.

    Pairs are drawn by walking a single cursor across the configured topics and
    templates (each advances independently via modulo), so the rotation cycles
    through topics while varying the template. Returns ``[]`` when no topics are
    configured. The cursor is persisted only when at least one pair is produced.
    """
    if n <= 0:
        return []
    topics = config.autopilot_topics()
    templates = config.autopilot_templates()
    if not topics or not templates:
        return []

    cursor = _read_cursor()
    pairs: list[tuple[str, str]] = []
    for offset in range(n):
        index = cursor + offset
        template = templates[index % len(templates)]
        topic = topics[index % len(topics)]
        pairs.append((template, topic))
    _write_cursor(cursor + len(pairs))
    return pairs
