"""social_video_factory — self-contained short-video ("brainrot") factory.

This package builds vertical 9:16 short videos through a staged pipeline:
idea -> script -> prompt -> generate -> import -> review -> render -> captions
-> awaiting human approval.  It NEVER auto-publishes.

Phase 1 implements the skeleton plus a fully working ``mock`` generation mode
that runs end-to-end even when ffmpeg/ffprobe are not installed (it degrades
gracefully).  Later phases add the browser-driven generation modes.

The package is deliberately self-contained: it does NOT import from the wider
Hermes ``agent/`` or ``tools/`` trees, so it can be tested without the full
dependency surface.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
