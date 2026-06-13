"""Module entry point so ``python -m social_video_factory`` works.

We delegate to :mod:`social_video_factory.cli` rather than duplicating the
``fire`` wiring here, keeping a single source of truth for the command surface.
"""

from __future__ import annotations

from social_video_factory.cli import main

if __name__ == "__main__":
    main()
