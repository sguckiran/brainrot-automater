"""Manual, human-driven login in a NORMAL (non-automated) browser.

WHY this is separate from the Playwright controller: Google (and others) refuse
sign-in inside an automation-controlled browser — "This browser or app may not
be secure". That detection fires on the automation flags / CDP that Playwright
launches Chrome with. So the human MUST log in via a plain Chrome instance.

The trick: launch plain Chrome on the SAME persistent ``user-data-dir`` the
automation later uses. Once you've signed in here, the session is stored in that
profile, and the Playwright runs simply REUSE it — they never log in, so they
never trip the automation check. This is not a bypass: a human logs in normally;
automation only reuses an existing session.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from social_video_factory import config


def _profile_and_url(target: str) -> tuple[Path, str]:
    """Resolve (persistent profile dir, start URL) for a login target.

    flow/gemini share the generation profile (``config.profile_dir()``);
    instagram/tiktok use their isolated publishing profiles — matching exactly
    what the controller / publisher use at runtime so the saved session lands in
    the right place.
    """
    t = target.strip().lower()
    if t == "flow":
        return config.profile_dir(), config.flow_url() or "https://labs.google/fx/tools/flow"
    if t == "gemini":
        return config.profile_dir(), config.gemini_url() or "https://gemini.google.com/"
    if t in {"instagram", "tiktok"}:
        url = (
            "https://www.instagram.com/"
            if t == "instagram"
            else "https://www.tiktok.com/login"
        )
        return config.social_profile_dir(t), url
    raise ValueError(f"unsupported login target: {target!r}")


def build_chrome_command(executable: str, profile_dir: Path, url: str) -> list[str]:
    """Plain-Chrome argv for a human login. PURE (no automation/CDP flags).

    Deliberately omits every automation signal (no --remote-debugging, no
    --enable-automation) so the browser looks like an ordinary one to the login
    page. ``--no-sandbox`` is needed because Chrome's sandbox can't initialize
    under WSL's default namespaces; it does NOT affect login detection.
    """
    return [
        executable,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        url,
    ]


def manual_login(
    target: str,
    *,
    wait: Callable[[str], object] = input,
    runner: Callable[[list[str]], object] | None = None,
) -> None:
    """Open a normal Chrome on ``target``'s profile and wait for a human login.

    ``wait``/``runner`` are injectable for tests. By default it launches Chrome
    as a background process, waits for the user to press Enter, then closes it.
    """
    profile_dir, url = _profile_and_url(target)
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable = config.browser_executable_path() or "google-chrome-stable"
    cmd = build_chrome_command(executable, profile_dir, url)

    if runner is not None:
        runner(cmd)
        return

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait(
            f"A normal Chrome window for '{target}' has opened on the virtual "
            "display.\nView it at your noVNC link, sign in by hand, then press "
            "Enter here to save the session and close it..."
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
