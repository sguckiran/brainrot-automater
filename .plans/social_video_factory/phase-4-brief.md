# Phase 4 Brief — queue mode + manual recovery

> Master design: `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read first).
> Phases 1–3 are DONE. Build ON TOP of: `pipeline.py` (reuse stages), `browser/worker.py` (`generate_in_browser`, `GenerationOutcome`), `store.py`, `media.py` (`find_latest_download`, `is_video_file`), `cli.py`.
> Implement ONLY Phase 4. Do NOT build Hermes tools (Phase 5) or docs (Phase 6).

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater`. In-repo, no worktree, no commit. `uv run` for pytest/ruff. No real browser/Playwright/network in tests — inject fakes.

## Hard safety constraints
Same as the worker: respect local rate limits, STOP the queue on any hard stop (`needs_human`), never bypass anything, no auto-publish.

## Scope

### `social_video_factory/browser/queue.py`
- `@dataclass QueueResult` = `{processed: int, outcomes: list[GenerationOutcome], stopped_reason: str | None}`.
- `run_queue(limit: int = 5, *, store=None, sleep=time.sleep, pause_seconds=None, generate=None) -> QueueResult`:
  - `store` defaults to `JobStore()`; `generate` defaults to `worker.generate_in_browser` (injected in tests); `pause_seconds` defaults to `config.min_seconds_between_generations()`.
  - **Select pending jobs**: `store.list_jobs(generation_mode=GenerationMode.BROWSER_FLOW.value)` filtered to "pending" = status in the pre-generation set `{created, idea, scripted, prompted}` (i.e. prepared but not yet generated/imported/failed/needs_human/awaiting_approval). Process oldest-first (stable order — sort by `created_at`). Cap at `limit`.
  - For each job: if it has no `prompt`, run `pipeline.run_idea/run_script/run_prompt/save_prompt_file` to prepare it. Then call `generate(job, store)`; append the outcome.
    - On `success`: if more jobs remain and we haven't hit `limit`, **pause** — `sleep(pause_seconds)` — so the next job clears the local min-gap, then continue.
    - On `needs_human` (hard stop) OR `error`: STOP the queue immediately, set `stopped_reason`, break.
    - On `rate_limited`: STOP the queue (no point continuing — caps/min-gap will keep denying), set `stopped_reason`, break.
  - Return the `QueueResult` (all outcomes stored regardless of stop).
- Keep it injectable + pure enough to unit-test with a fake `generate` and a no-op `sleep` (no real browser).

### CLI — extend `social_video_factory/cli.py`
- `browser_run_queue(limit: int = 5)` (fire: `browser-run-queue`): call `queue.run_queue(limit)`, print a JSON summary `{processed, stopped_reason, outcomes: [...]}`. Exit 0 normally; if `stopped_reason` indicates a hard stop / error, still exit 0 (the run completed and recorded outcomes) — but print the stop reason prominently. Register in `main()`.
- `import_latest_browser_download(job_id)` (fire: `import-latest-browser-download`): manual-recovery path for when the worker paused and you clicked download yourself.
  - load job (missing → stderr + exit 2).
  - `latest = media.find_latest_download(config.downloads_dir())`; if None → stderr "no video download found in <dir>" + exit 5.
  - `pipeline.run_import(job, store, src_path=latest)` then `run_review` → `run_render` → `run_captions` → `finalize_approval` (REUSE Phase-1 stages — this is the same tail the worker runs).
  - print the resulting job summary JSON; exit 0.
  - Register in `main()`.
- **Optional DRY** (only if low-risk): add `pipeline.finish_after_import(job, store)` = `run_review`→`run_render`→`run_captions`→`finalize_approval`, and call it from BOTH `import-latest` here and (refactor) the worker's tail. If refactoring the worker feels risky, just reuse the four stage calls directly and skip the worker refactor. Do NOT regress any Phase-3 test.

## Tests — add to `tests/social_video_factory/`
- `test_queue.py`: 
  - selects ONLY pending `browser_flow` jobs (ignores `mock` jobs, `awaiting_approval`/`needs_human`/`failed` ones, and other modes); respects `limit`; processes oldest-first.
  - a fake `generate` returning `success` for several jobs → `processed == min(limit, pending)`, `sleep` called between successes (count = processed-1), `stopped_reason is None`.
  - a fake `generate` returning `needs_human` on the 2nd job → queue STOPS (3rd not processed), `stopped_reason` set, outcomes length == 2.
  - `rate_limited` outcome → stops.
  - a job with no prompt gets prepared (prompt populated) before `generate` is called.
- `test_import_latest.py`:
  - with a video file in the downloads dir → imports + reaches `awaiting_approval` (ffmpeg absent → render skipped gracefully); `imported_media_path` set.
  - empty downloads dir → the CLI path raises `SystemExit(5)` (call the function directly).
- All tests set `SOCIAL_FACTORY_DATA_DIR` to tmp. No real browser/network.

## Definition of done (report back explicitly)
1. All files created/edited.
2. `uv run pytest tests/social_video_factory/ -q` passes (paste summary; Phases 1–3 still green).
3. `uv run ruff check social_video_factory/ tests/social_video_factory/` clean (paste).
4. Public signatures of `run_queue`/`QueueResult`, the two new CLI commands, and (if added) `pipeline.finish_after_import`.
5. A short note confirming the queue stops on hard-stop/rate-limited and pauses between successes; and that import-latest reuses the existing pipeline tail.
6. Any deviations and why.
