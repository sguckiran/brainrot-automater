# Phase 5 Brief — Hermes tools registration

> Master design: `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read first).
> Phases 1–4 are DONE. Expose the package to the Hermes agent as 4 self-registering tools.
> Implement ONLY Phase 5. Docs/packaging/polish are Phase 6.

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater`. In-repo, no worktree, no commit. `uv run` for pytest/ruff.

## Pattern to follow
`tools/video_generation_tool.py` — especially the `registry.register(name=..., toolset=..., schema=..., handler=..., check_fn=..., requires_env=[], is_async=False, emoji=...)` call at the bottom (line ~552), the `check_fn() -> bool` shape (line ~ `check_video_generation_requirements`), and `handler(args: dict, **kwargs) -> str` returning a JSON string (use `json.dumps`; `from tools.registry import registry, tool_error`). Tools self-register at import; `tools/registry.py::discover_builtin_tools` auto-imports any `tools/*.py` containing a top-level `registry.register(...)`.

## CRITICAL — non-interactive safety
The worker (`generate_in_browser`) and queue use `input()` in two places: the rate-limit human-confirm gate (via `RateLimiter.confirm`) and the selector `manual_pause` (via `controller.wait_for_enter`). If a Hermes tool calls these and a pause is hit, the AGENT WOULD HANG on stdin. The tools MUST run NON-INTERACTIVELY and never block.

Achieve this WITHOUT modifying `worker.py` / `selectors.py` / `rate_limit.py` (they are audited + stable). In `tools/social_video_factory_tool.py`:
- Inject a `RateLimiter(confirm=lambda _msg: False)` so a due human-confirm cleanly returns a `needs_human` outcome instead of blocking on stdin.
- Wrap the controller in a tiny adapter whose `wait_for_enter(...)` is a NON-BLOCKING no-op (it may print/log the message but must NOT read stdin), delegating every other method to the real controller via `__getattr__`. Pass this wrapped controller into `generate_in_browser`. Net effect: a `manual_pause` records its note and returns immediately; the worker's existing downstream checks (no video found, etc.) then resolve to a `needs_human` outcome with artifacts — no hang.
- Define this adapter privately in the tool module (e.g. `class _NonBlockingController`).

## Scope — `tools/social_video_factory_tool.py`

Four tools, toolset `"social_video_factory"`, each `handler(args, **_kw) -> str` returning JSON, registered via `registry.register(...)`. Use a shared `check_fn` `_svf_available() -> bool` that returns True when the `social_video_factory` package imports (it always does in-repo); do NOT require Playwright for availability (the login tool and import tool work without it). Lazy-import `social_video_factory.*` INSIDE the handlers/check (keep module import cheap and avoid import cycles at `tools` discovery time).

1. **`social_video_factory_browser_login`** — params: `target` (enum `flow|gemini`, default `flow`), `url` (optional string).
   - Login REQUIRES manual human interaction at a terminal, which a tool cannot drive. So this tool does NOT attempt to drive login. It returns JSON guidance: the exact command to run (`python -m social_video_factory.cli browser-login --target <target>`), the resolved URL (or a note that `SOCIAL_FACTORY_FLOW_URL`/`SOCIAL_FACTORY_GEMINI_URL` must be set), and whether the persistent profile dir already exists / appears initialized (`config.profile_dir()` exists and is non-empty). This is the safe, honest behavior — never claims to have logged in, never bypasses login.

2. **`social_video_factory_browser_generate_job`** — params: `job_id` (required string).
   - Load the job (`JobStore().load`); if missing → `tool_error`/JSON error. Ensure prompt (run `pipeline.run_idea/run_script/run_prompt/save_prompt_file` if absent, else load from `prompt_path`). Call `generate_in_browser(job, store, controller=<non-blocking wrapped get_controller()>, rate_limiter=RateLimiter(confirm=lambda _:False))`. Catch `BrowserUnavailable` → JSON error with the remediation text. Return JSON: `{status, job_id, downloaded_path, reason, job_status}`.

3. **`social_video_factory_browser_run_queue`** — params: `limit` (int, default 5).
   - Call `queue.run_queue(limit, generate=<a closure that calls generate_in_browser with the non-blocking controller + non-interactive rate limiter>)`. (Inject `generate` so the queue's per-job calls are also non-interactive.) Return JSON `{processed, stopped_reason, outcomes: [...]}`.

4. **`social_video_factory_import_latest_browser_download`** — params: `job_id` (required string).
   - Load job (missing → JSON error). `media.find_latest_download(config.downloads_dir())`; None → JSON error "no video download found in <dir>". Else `pipeline.run_import` + `pipeline.finish_after_import`. Return the job summary JSON `{id, status, imported_media_path, rendered_path, captions, ...}`.

Each tool's schema `description` must briefly state the safety posture (drives the user's OWN logged-in profile; never bypasses login/limits/safety; no auto-publish). `emoji` e.g. 🎬 / 🔐 / 📥.

## Tests — `tests/social_video_factory/test_hermes_tools.py`
- All four tools register: import `tools.social_video_factory_tool`, then assert each name is in `registry` (use the registry's lookup API — check how `tests/` query the registry, or import the registry and inspect). `check_fn` returns True.
- `social_video_factory_browser_login` handler returns valid JSON containing the CLI command and a `profile_exists` boolean; with no URL configured it still returns guidance (no exception), and it NEVER opens a browser.
- `social_video_factory_browser_generate_job` with a missing job_id → JSON error (no exception).
- `social_video_factory_import_latest_browser_download` with an empty downloads dir → JSON error mentioning no download.
- A test proving NON-BLOCKING: construct the `_NonBlockingController` wrapping a fake controller and assert `wait_for_enter` returns immediately without reading stdin (e.g. monkeypatch `builtins.input` to raise — it must NOT be called).
- `social_video_factory_browser_generate_job` happy path with a FAKE non-blocking controller + fake resolver/locators (reuse the Phase-3 worker test fakes/approach) reaching `success` → tool returns `status="success"`. (If wiring a full fake through the tool is heavy, at minimum assert the tool injects a non-interactive rate limiter and non-blocking controller — e.g. monkeypatch `generate_in_browser` to capture kwargs and assert `rate_limiter.confirm(...) is False` and the controller's `wait_for_enter` is non-blocking.)
- All tests set `SOCIAL_FACTORY_DATA_DIR` to tmp. No real browser/Playwright/network. Phases 1–4 tests must stay green.

## Definition of done (report back explicitly)
1. `tools/social_video_factory_tool.py` created with all 4 tools registered; test file added.
2. `uv run pytest tests/social_video_factory/ -q` passes (paste summary; Phases 1–4 still green).
3. `uv run ruff check tools/social_video_factory_tool.py tests/social_video_factory/` clean (paste).
4. Confirm the tool module is auto-discovered: run a quick `uv run python -c "from tools.registry import registry; import tools.social_video_factory_tool; print([n for n in registry... if 'social_video_factory' in n])"` (adapt to the registry's actual API) and paste the 4 names.
5. The 4 tool names, their params, and the check_fn name.
6. A short note confirming: no `input()`/stdin blocking is reachable from any tool; `worker.py`/`selectors.py`/`rate_limit.py` were NOT modified; login tool never claims to bypass/perform login. Any deviations and why.
