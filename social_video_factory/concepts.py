"""Generate varied short-video concepts without requiring a model call.

There are TWO concept *categories*, chosen at random per video so the channel
isn't all one thing:

* ``action``    — an anthropomorphic creature pulling off a dynamic, fast-paced
  stunt/scene (the original "brainrot" style).
* ``fruit_talk`` — anthropomorphic fruits with human features (faces, arms,
  expressions) in a CONVERSATIONAL scene: they talk to / argue with / gossip
  about each other. By design this category only ever produces dialogue-driven
  videos — the constraint lives in the word-banks below, so it can't drift into
  action scenes.

Each call returns ONE concept and persists its signature so the same exact
combination is not reused until the whole space is exhausted.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

from social_video_factory import config

_HISTORY_FILE = "concept_history.json"

# --- Category: action (dynamic creature stunts) ----------------------------

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

# --- Category: fruit_talk (conversational anthropomorphic fruit) -----------

FRUITS = (
    "a grumpy strawberry with stubby little arms and a wrinkled face",
    "a smug avocado with bushy eyebrows and a half-smirk",
    "a nervous banana with darting eyes and fidgety hands",
    "a cheerful orange with chubby cheeks and a wide grin",
    "a sarcastic lemon with a permanent eye-roll",
    "a dramatic grape with long eyelashes and a trembling lip",
    "a tired pineapple with droopy eyes and slumped shoulders",
    "a hyperactive kiwi with tiny legs and a manic smile",
    "a posh pear with a monocle and an upturned nose",
    "a tough coconut with a square jaw and crossed arms",
    "a sweet peach with rosy cheeks and a shy expression",
    "a moody blueberry with a tiny scowl and folded arms",
)
# Every entry is a TALKING/arguing interaction — this is what keeps the
# category strictly conversational.
EXCHANGES = (
    "argue loudly about which of them is the better fruit",
    "gossip in hushed voices about the vegetables in the next aisle",
    "have a heated debate over who belongs in the smoothie",
    "bicker through an awkward breakup conversation",
    "trade increasingly petty insults back and forth",
    "negotiate a shaky peace treaty after a food fight",
    "complain to each other about being left in the fridge too long",
    "roast each other's ripeness without mercy",
    "argue over the last open spot in the fruit bowl",
    "give each other terrible, overconfident life advice",
    "interrupt and talk over each other in a rising argument",
    "share dramatic secrets, then immediately deny them",
)
FRUIT_SETTINGS = (
    "on a sunlit kitchen counter",
    "crammed together inside a crowded fruit bowl",
    "on a supermarket shelf after closing time",
    "inside a humming refrigerator",
    "at a tiny outdoor picnic table",
    "balanced on a wooden chopping board",
    "waiting nervously beside a blender",
    "at a fancy fruit-platter party",
)
FRUIT_MOODS = (
    "tense and passive-aggressive",
    "warm but secretly competitive",
    "explosively dramatic and over-the-top",
    "deadpan and sarcastic",
    "weepy and wildly over-emotional",
    "smug and insufferably superior",
)
FRUIT_TREATMENTS = (
    "glossy Pixar-style 3D with soft studio lighting",
    "warm claymation with tactile, hand-pressed textures",
    "photoreal CGI fruit with expressive cartoon faces",
    "bright children's-book illustration brought to life",
)
FRUIT_CAMERAS = (
    "shot/reverse-shot close-ups cutting between the two faces as they speak",
    "slow push-in on each fruit as it delivers a line",
    "locked two-shot framing both fruits mid-conversation",
    "handheld close-ups catching every exaggerated expression",
)

# Ordered category registry: (name, banks-tuple, builder).
_ACTION_BANKS = (SUBJECTS, SETTINGS, ACTIONS, TWISTS, TREATMENTS, CAMERAS)
_FRUIT_BANKS = (FRUITS, FRUITS, EXCHANGES, FRUIT_SETTINGS, FRUIT_MOODS, FRUIT_TREATMENTS, FRUIT_CAMERAS)


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


def _banks_for(category: str) -> tuple[tuple[str, ...], ...]:
    return _ACTION_BANKS if category == "action" else _FRUIT_BANKS


def _total_combinations() -> int:
    total = 0
    for banks in (_ACTION_BANKS, _FRUIT_BANKS):
        product = 1
        for bank in banks:
            product *= len(bank)
        total += product
    return total


def _build_action(indexes: tuple[int, ...], theme_note: str) -> str:
    subject, setting, action, twist, treatment, camera = (
        bank[index] for bank, index in zip(_ACTION_BANKS, indexes)
    )
    return (
        f"{subject} {action} {setting}, {twist}. "
        f"High-energy, fast-paced, dynamic motion. "
        f"Visual treatment: {treatment}. Camera: {camera}.{theme_note}"
    )


def _build_fruit(indexes: tuple[int, ...], theme_note: str) -> str:
    a_idx, b_idx, ex_idx, set_idx, mood_idx, treat_idx, cam_idx = indexes
    # Guarantee two DIFFERENT fruits (the point is a conversation between two).
    if b_idx == a_idx:
        b_idx = (b_idx + 1) % len(FRUITS)
    fruit_a = FRUITS[a_idx]
    fruit_b = FRUITS[b_idx]
    exchange = EXCHANGES[ex_idx]
    setting = FRUIT_SETTINGS[set_idx]
    mood = FRUIT_MOODS[mood_idx]
    treatment = FRUIT_TREATMENTS[treat_idx]
    camera = FRUIT_CAMERAS[cam_idx]
    return (
        f"A conversational scene: {fruit_a} and {fruit_b} {exchange} {setting}. "
        f"They are anthropomorphic fruits with human faces and arms who talk to "
        f"each other; the tone is {mood}. Dialogue-driven and character-focused, "
        f"paced to land each line with clear lip-sync and reactions. "
        f"Visual treatment: {treatment}. Camera: {camera}.{theme_note}"
    )


def generate_concept(theme: str = "") -> str:
    """Return and persist a concept not used in recent history.

    Randomly picks between the ``action`` and ``fruit_talk`` categories on each
    call. The ``fruit_talk`` category is always a conversation between two
    anthropomorphic fruits (never an action scene).
    """
    history = _read_history()
    used = set(history)
    if len(used) >= _total_combinations():
        history = []
        used.clear()

    builders = {"action": _build_action, "fruit_talk": _build_fruit}
    theme_note = f" Inspired by the theme '{theme.strip()}'." if theme.strip() else ""

    # Re-pick the category each attempt so an exhausted category can't deadlock
    # the loop — the other category still has unused combinations.
    while True:
        category = "action" if secrets.randbelow(2) == 0 else "fruit_talk"
        banks = _banks_for(category)
        indexes = tuple(secrets.randbelow(len(bank)) for bank in banks)
        signature = ":".join((category, *map(str, indexes)))
        if signature not in used:
            break

    history.append(signature)
    _write_history(history)
    return builders[category](indexes, theme_note)
