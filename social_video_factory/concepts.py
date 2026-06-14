"""Generate varied short-video concepts without requiring a model call."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

from social_video_factory import config

_HISTORY_FILE = "concept_history.json"

SUBJECTS = (
    "an orange cat DJ",
    "a tuxedo cat detective",
    "a tiny cat astronaut",
    "a fluffy cat chef",
    "a cyberpunk alley cat",
    "a claymation kitten inventor",
    "a royal cat knight",
    "a cat stunt driver",
    "a ghost cat conductor",
    "a miniature cat mechanic",
)
SETTINGS = (
    "inside a neon food truck",
    "on a moon-base dance floor",
    "in a rain-soaked miniature city",
    "inside an abandoned subway station",
    "on a tropical pirate island",
    "inside a clockwork castle",
    "on a rooftop above a futuristic city",
    "inside a zero-gravity kitchen",
    "at a glowing midnight carnival",
    "inside a giant arcade machine",
)
ACTIONS = (
    "conducts an impossible orchestra",
    "chases a runaway noodle tornado",
    "repairs a failing rocket",
    "escapes a collapsing obstacle course",
    "drifts through a high-speed race",
    "builds a machine from flying parts",
    "duels a shadow made of smoke",
    "surfs a wave of sparkling objects",
    "solves a rapidly changing puzzle",
    "catches a bouncing ball of light",
)
TWISTS = (
    "and the final impact resets the opening frame",
    "before everything freezes except the cat",
    "and every movement changes the world around it",
    "before the tiny prop becomes enormous",
    "and the apparent enemy joins the performance",
    "before gravity suddenly reverses",
    "and the last spark becomes the first scene's light",
    "before the whole set folds into a toy box",
)
TREATMENTS = (
    "cinematic neon realism with saturated rim lighting",
    "handmade claymation with tactile textures",
    "colorful stop-motion miniature photography",
    "high-contrast noir with selective glowing color",
    "polished animated-film lighting and expressive motion",
    "retro-futurist arcade visuals with crisp reflections",
)
CAMERAS = (
    "fast push-in followed by a smooth orbit",
    "low-angle tracking shot with a whip-pan payoff",
    "macro opening that pulls back to reveal the full scene",
    "locked centered framing with escalating action toward camera",
    "overhead dive into a close tracking shot",
    "single continuous dolly move ending on a match cut",
)


def _history_path() -> Path:
    return config.state_dir() / _HISTORY_FILE


def _read_history() -> list[str]:
    try:
        data = json.loads(_history_path().read_text(encoding="utf-8"))
        values = data.get("signatures", [])
        return [str(value) for value in values if value]
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def _write_history(signatures: list[str]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".concept.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"signatures": signatures}, fh, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def generate_concept(theme: str = "") -> str:
    """Return and persist a concept not used in recent history."""
    sizes = (
        len(SUBJECTS),
        len(SETTINGS),
        len(ACTIONS),
        len(TWISTS),
        len(TREATMENTS),
        len(CAMERAS),
    )
    history = _read_history()
    used = set(history)
    total_combinations = 1
    for size in sizes:
        total_combinations *= size
    if len(used) >= total_combinations:
        history = []
        used.clear()

    while True:
        indexes = tuple(secrets.randbelow(size) for size in sizes)
        signature = ":".join(map(str, indexes))
        if signature not in used:
            break
    history.append(signature)
    _write_history(history)

    subject, setting, action, twist, treatment, camera = (
        collection[index]
        for collection, index in zip(
            (SUBJECTS, SETTINGS, ACTIONS, TWISTS, TREATMENTS, CAMERAS),
            indexes,
        )
    )
    theme_note = f" Inspired by the theme '{theme.strip()}'." if theme.strip() else ""
    return (
        f"{subject} {action} {setting}, {twist}. "
        f"Visual treatment: {treatment}. Camera: {camera}.{theme_note}"
    )
