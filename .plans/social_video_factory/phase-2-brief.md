# Phase 2 Brief — browser controller + selectors + `browser-login`

> Master design: `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read first).
> Phase 1 is DONE (package skeleton, config, models, store, pipeline, cli). Build ON TOP of it.
> Implement ONLY Phase 2. Do NOT build the worker / hard-stops / rate-limit (Phase 3) or Hermes tools (Phase 5).

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater`. Work in-repo, no worktree, no commit.

## Hard safety constraints (from the master plan — enforce in code + comments)
NO stealth, NO fingerprint spoofing, NO anti-detection flags (in particular do **NOT** add `--disable-blink-features=AutomationControlled` or similar), NO CAPTCHA solving, NO proxy/account rotation, NO bypass of login/limits/safety. The browser drives the user's OWN logged-in profile only.

## Scope

### `social_video_factory/browser/__init__.py`

### `social_video_factory/browser/controller.py`
- `BrowserController` — abstract base (the "clean browser-controller abstraction" the plan requires). Methods/contract (sync API):
  - `start() -> None` — launch and hold a browser + page.
  - `goto(url: str, *, wait_until="domcontentloaded", timeout_ms=30000) -> None`
  - `page` property → the underlying page object (Phase 3 worker + selectors use it).
  - `screenshot(path) -> Path|None`
  - `html() -> str` (full page HTML, for snapshots)
  - `expect_download(trigger: Callable[[], None], timeout_ms) -> Path` — run `trigger` and capture the resulting download to the downloads dir; return saved path. (Wrap Playwright `page.expect_download`.)
  - `wait_for_enter(message: str) -> None` — print message, block on `input()` (used by login + manual pause).
  - `close() -> None`; also support use as a context manager (`__enter__/__exit__`).
- `PlaywrightController(BrowserController)` — implements it with `playwright.sync_api`:
  - Lazy-import Playwright at `start()` time via `tools.lazy_deps.ensure("social_video_factory.browser")` (you will ADD this key to `tools/lazy_deps.py` — see Packaging below). On `FeatureUnavailable`/`ImportError`, raise a clear `BrowserUnavailable` error whose message tells the user to `pip install playwright` AND run `python -m playwright install chromium` (pip cannot fetch the browser binary).
  - Launch with `chromium.launch_persistent_context(user_data_dir=config.profile_dir(), headless=config.browser_headless(), accept_downloads=True, downloads_path=config.downloads_dir(), executable_path=config.browser_executable_path() or None)`. Mirror the in-repo precedent `plugins/google_meet/meet_bot.py:514` BUT persistent + headed and **without any stealth/launch-args**. Use the context's existing/`new_page()`.
  - `expect_download` uses `page.expect_download()`; save via `download.save_as(downloads_dir / download.suggested_filename)`.
- `NullController(BrowserController)` — used when Playwright is unavailable: every method raises `BrowserUnavailable` with the same remediation message. This is the clean fallback the plan asks for.
- `get_controller() -> BrowserController` — factory: try to construct `PlaywrightController` (deferring the actual import to `start()`), but if Playwright clearly can't be imported, return `NullController`. Keep it simple and testable (allow monkeypatching the import check).
- `class BrowserUnavailable(RuntimeError)`.

### `social_video_factory/browser/selectors.py`
- Load selector config: user override from `config.selectors_file()` if set, else the bundled `social_video_factory/browser_selectors.example.yaml`. Use `yaml.safe_load` (pyyaml is a core dep). Cache parse.
- `class SelectorResolver` constructed with `(page, config: dict, target: str, controller)`. Layered `.locate(action_key) -> locator|None`:
  1. configured CSS/text selectors from YAML for `<target>.<action_key>` (try each in order),
  2. accessible queries — Playwright `page.get_by_role(...)` / `page.get_by_label(...)` using role/label hints from YAML,
  3. visible button text — `page.get_by_text(...)` / role=button name,
  4. **manual pause** fallback: `.manual_pause(reason)` saves a screenshot (best-effort), prints the action needed + the downloads dir, and blocks via `controller.wait_for_enter(...)`, then returns `None` so the caller proceeds from whatever the human did.
- Keep the resolution layering pure enough to unit-test with a FAKE page (duck-typed object whose `query_selector`/`get_by_role`/etc. are stubs). Do NOT require real Playwright in tests.
- The YAML schema keys (document them in the example file): per target (`flow`, `gemini`) — `prompt_box`, `submit`, `generating_indicator`, `download`, `export_mp4`, `result_video`; plus a top-level `hard_stops` map (text patterns) reserved for Phase 3 (define the keys, leave them for Phase 3 to consume).

### `social_video_factory/browser_selectors.example.yaml`
Editable, heavily commented. Explain it is the file users tweak when the Gemini/Flow web UI changes, that selectors are tried in order, and that an empty/garbage selector simply falls through to the accessible/text/manual layers. Provide plausible-but-clearly-placeholder selectors (comment that they WILL need updating against the live UI) for `flow.*` and `gemini.*`, plus the `hard_stops` text-pattern keys (login, captcha, suspicious activity, rate/usage limit, subscription upgrade, payment, safety refusal, content policy, age/identity verification, account recovery, consent/policy modal).

### CLI — extend `social_video_factory/cli.py`
Add `browser_login(target="flow", url=None)` (fire: `browser-login`):
- resolve URL: explicit `url` arg → else `config.flow_url()`/`config.gemini_url()` by target → if empty, print a clear message that the URL must be set via `SOCIAL_FACTORY_FLOW_URL`/`SOCIAL_FACTORY_GEMINI_URL` (or `--url`) and exit non-zero.
- `get_controller()`, `start()`, `goto(url)`, then `wait_for_enter("Log in manually in the opened browser, then press Enter here to save the session and exit...")`, then `close()`. The persistent profile dir captures the session automatically (no cookie/token handling in our code, nothing logged).
- Wrap `BrowserUnavailable` to print the remediation cleanly and exit non-zero.

## Packaging / wiring (Phase 2 portion only)
- `tools/lazy_deps.py`: add to `LAZY_DEPS` (near line 77, pick a sensible section): `"social_video_factory.browser": ("playwright==1.60.0",)`.
- `.gitignore`: add `.social_video_factory/` (ignore the runtime data root) if not already ignored.
- `.env.example`: append a documented block for all `SOCIAL_FACTORY_*` vars (defaults from the master plan).
- **Do NOT** edit `pyproject.toml` `[tool.setuptools.packages.find]` or the optional-extra or regenerate `uv.lock` in this phase — that is deferred to Phase 6 to avoid disturbing the `uv run` env the phase agents rely on. (Runtime install happens via the lazy_deps entry; tests run against the source tree via `uv run`.)

## Tests — add to `tests/social_video_factory/`
- `test_browser_controller.py`: `NullController` methods raise `BrowserUnavailable` with remediation text; `get_controller()` returns `NullController` when the playwright import is forced to fail (monkeypatch); `PlaywrightController` does NOT import playwright at construction (only at `start()`), and `start()` raises `BrowserUnavailable` cleanly when the lazy import fails. Assert NO stealth args anywhere in the module source (e.g. read the file, assert `AutomationControlled` not present).
- `test_selectors.py`: bundled example YAML parses and has the documented keys for `flow`/`gemini`/`hard_stops`; `SelectorResolver.locate` returns the configured hit first; falls back through role → text → manual pause using a FAKE page; `manual_pause` calls `wait_for_enter` (monkeypatched) and returns None.
- All tests set `SOCIAL_FACTORY_DATA_DIR` to tmp. No real browser, no playwright install, no network.

## Environment / running
- Use `uv run` for everything (`uv run pytest tests/social_video_factory/ -q`, `uv run ruff check social_video_factory/ tests/social_video_factory/`). System `python` (3.14) is unusable.
- Playwright is NOT installed and you must NOT install it or download chromium. Everything is tested via fakes/mocks.

## Definition of done (report back explicitly)
1. All files created/edited as above.
2. `uv run pytest tests/social_video_factory/ -q` passes (paste summary; Phase 1 tests must still pass).
3. `uv run ruff check social_video_factory/ tests/social_video_factory/` clean (paste).
4. Confirm (paste the grep result) that the browser module contains NO stealth/anti-detection flags.
5. Public signatures of `BrowserController`, `PlaywrightController`, `NullController`, `get_controller`, `SelectorResolver`, and the new `browser-login` CLI command.
6. Note any deviations and why.
