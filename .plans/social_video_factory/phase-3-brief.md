# Phase 3 Brief — browser worker + hard stops + rate limiting

> Master design: `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read first).
> Phases 1 & 2 are DONE. Build ON TOP of: `social_video_factory/config.py, models.py, store.py, pipeline.py` (reuse its stage functions), and `social_video_factory/browser/{controller,selectors}.py`.
> Implement ONLY Phase 3. Do NOT build queue mode / import-latest (Phase 4) or Hermes tools (Phase 5).

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater`. In-repo, no worktree, no commit. Use `uv run` for pytest/ruff. No real browser / no Playwright install / no network in tests — use FAKES + dependency injection.

## Hard safety constraints (enforce in code + comments)
The worker is CONSERVATIVE. It must NOT bypass anything. On ANY blocking/unusual screen it stops, screenshots, marks the job `needs_human`, and exits cleanly. NO stealth, NO CAPTCHA solving, NO limit/login/safety bypass, NO proxy/account rotation. Local rate limits are ALWAYS respected even if the website would allow more. Never log/print cookies, tokens, or secrets. No auto-publish.

## Scope

### `social_video_factory/browser/hard_stops.py`
- Consumes the `hard_stops` text-pattern map from the selector YAML (loaded via `selectors.load_selector_config()`), keys already defined in Phase 2: `login, captcha, suspicious_activity, rate_limit, subscription_upgrade, payment, safety_refusal, content_policy, age_identity_verification, account_recovery, consent_policy_modal`.
- `detect_hard_stop(page_text: str, config: dict | None = None) -> str | None` — PURE: lower-cases the page text, returns the FIRST hard-stop key whose any pattern is a substring, else None. Pattern source = YAML `hard_stops` merged over a built-in default set of robust English phrases (so detection works even if the user's YAML omits a category). Define the built-in defaults in this module.
- `HARD_STOP_KEYS` tuple for callers/tests. Testable on canned HTML/text with zero Playwright.

### `social_video_factory/browser/artifacts.py`
- `ArtifactLogger(job_id, controller)` writing under `config.logs_dir() / job_id /`. `stage(name, *, selector_used=None, note=None, screenshot=True, html=False)` saves: a screenshot (best-effort via `controller.screenshot`), optional HTML snapshot, and appends a JSONL event `{stage, ts (ISO), selector_used, note}`. 
- `redact(text) -> str` — strip obvious secrets before anything is written/printed: cookie/token/authorization/password/api-key/bearer patterns and long opaque values. HTML snapshots MUST be passed through `redact` (and skip storing `<script>`/cookie content). NEVER write raw cookies/tokens. Unit-test the redaction.

### `social_video_factory/rate_limit.py` (top-level package module)
- `RateLimiter` persisting `config.state_dir() / "rate_limit.json"` = `{generations: [iso_ts, ...], total_count: int}` (atomic write like `store.py`). Inject a `now: Callable[[], datetime]` and a `confirm: Callable[[str], bool]` for testability (defaults: real clock, and a `input()`-based y/N confirm).
- Reads thresholds from `config.max_generations_per_hour/_per_day/min_seconds_between_generations/require_human_confirm_every()`.
- `check() -> RateDecision` (dataclass `{allowed: bool, reason: str|None, needs_human_confirm: bool}`): denies (allowed=False) if last-hour count >= hourly cap, last-day count >= daily cap, or seconds since last generation < min gap. Sets `needs_human_confirm=True` when `(total_count % require_human_confirm_every) == 0` and the cap > 0.
- `record() -> None` — append `now()` to generations, increment `total_count`, persist.
- Helper to prune timestamps older than a day on load. Keep it dependency-light (stdlib + config).

### `social_video_factory/browser/worker.py`
- `@dataclass GenerationOutcome` = `{status: str, job_id: str, downloaded_path: str|None, reason: str|None}` where status ∈ `success | needs_human | rate_limited | error`.
- `generate_in_browser(job, store, *, controller=None, rate_limiter=None, selectors_config=None, artifacts=None, poll_timeout_s=600, poll_interval_s=5) -> GenerationOutcome`. Everything injectable for tests; defaults wire the real `get_controller()`, `RateLimiter()`, `load_selector_config()`, `ArtifactLogger`.
- Flow (CONSERVATIVE — re-check hard stops at each major step; on any selector miss, call `resolver.manual_pause(...)` then continue from human action):
  1. **Rate-limit gate FIRST** — `decision = rate_limiter.check()`. If not allowed: add a history note (e.g. "rate limited: <reason>"), persist, return `rate_limited` (do NOT open the browser). If `needs_human_confirm` and the injected confirm returns False: return `needs_human` with reason "human confirm declined".
  2. Resolve target URL from `job.target` (`flow`→`config.flow_url()`, `gemini`→`config.gemini_url()`). If empty → return `error` with a clear reason (URL must be configured). 
  3. `controller.start()`, `controller.goto(url)`; artifacts.stage("opened").
  4. **Hard-stop check** on `controller.html()` (or visible text). If hit: screenshot, `job.advance(JobStatus.NEEDS_HUMAN, note=...)`, set `job.needs_human_reason`, persist, `controller.close()`, return `needs_human`.
  5. Build `SelectorResolver(page, cfg, job.target, controller)`. Locate `prompt_box`; paste the prompt via the locator (`fill`/`type`); if no locator → `manual_pause("paste this prompt into the box: ...")`. artifacts.stage("prompt_pasted", selector_used=...).
  6. **Submit only if UI ready**: verify the prompt box has content / the submit control is present+enabled before clicking `submit`; if not ready or no locator → `manual_pause`. Re-check hard stops after submit.
  7. **Wait for generation**: poll up to `poll_timeout_s` for the `generating_indicator` to clear / `result_video` to appear, re-running the hard-stop check each iteration (a refusal/limit can appear mid-generation → needs_human). On timeout → `manual_pause("generation is taking too long; complete/download manually")`.
  8. **Download/export**: use `controller.expect_download(trigger=lambda: click download)` to capture the file; if the UI prompts for a format, prefer MP4/video (`export_mp4`). If no download captured (selector miss / manual) → `manual_pause`, then fall back to `media.find_latest_download(config.downloads_dir())`.
  9. Verify the captured file is a video (`media.is_video_file`); if not → `needs_human` ("no video download found").
  10. `rate_limiter.record()`. Set `job.raw_media_path`. 
  11. **Continue the pipeline by REUSING Phase-1 stages**: `pipeline.run_import(job, store, src_path=downloaded)` → `run_review` → `run_render` → `run_captions` → `finalize_approval`. Return `success` with `downloaded_path`.
- Any unexpected exception → screenshot (best-effort), record `job.error`, set status `failed` (or `needs_human` if it's clearly a UI/blocking situation), persist, close, return `error`. Always `controller.close()` in a `finally`.

### CLI — extend `social_video_factory/cli.py`
Add `browser_generate(job_id)` (fire: `browser-generate`):
- load job via `JobStore`; if missing → stderr + exit 2.
- if `job.generation_mode` is not `browser_flow` → warn but proceed (still usable).
- if no `job.prompt`/`prompt_path` → run `pipeline.run_idea/run_script/run_prompt/save_prompt_file` to populate it (so a bare job still works), else load the saved prompt.
- call `generate_in_browser(job, store)`; print the `GenerationOutcome` as JSON; exit non-zero on `error`/`needs_human` so scripts can branch (0 for success/rate_limited? — use 0 for success, 3 for needs_human, 4 for rate_limited, 1 for error). Catch `BrowserUnavailable` → remediation + exit 1.
- Register `"browser-generate": browser_generate` in `main()`.

## Tests — add to `tests/social_video_factory/`
- `test_hard_stops.py`: each category detected on a canned snippet; clean page → None; user-YAML pattern merges with defaults.
- `test_rate_limit.py`: hourly cap denies the (cap+1)th within the hour; daily cap; min-gap denial with injected clock; pruning of >24h-old entries; `needs_human_confirm` cadence; persistence round-trip (atomic).
- `test_artifacts.py`: `redact` removes cookie/token/bearer/api-key/password values; `stage` writes a JSONL event + screenshot file (with a fake controller); HTML snapshot is redacted.
- `test_worker.py` (FAKE controller + fake resolver/locators, injected rate limiter & confirm; ffmpeg absent):
  - happy path → `success`, job reaches `awaiting_approval`, `record()` called once.
  - hard-stop page → `needs_human`, `job.needs_human_reason` set, browser closed, NO `record()`.
  - rate-limited → `rate_limited`, browser NEVER started.
  - selector miss on prompt_box → `manual_pause` invoked (monkeypatched `wait_for_enter`) then proceeds.
- All tests set `SOCIAL_FACTORY_DATA_DIR` to tmp. No real browser/Playwright/network.

## Definition of done (report back explicitly)
1. All files created/edited.
2. `uv run pytest tests/social_video_factory/ -q` passes (paste summary; Phases 1 & 2 still green).
3. `uv run ruff check social_video_factory/ tests/social_video_factory/` clean (paste).
4. Public signatures of `detect_hard_stop`, `RateLimiter`, `ArtifactLogger`/`redact`, `generate_in_browser`/`GenerationOutcome`, and the `browser-generate` CLI command.
5. A short note confirming: rate gate runs before opening the browser; hard stops are re-checked during the generation wait; every selector miss falls back to manual pause; nothing bypasses login/limits/safety; no secrets logged.
6. Any deviations and why.
