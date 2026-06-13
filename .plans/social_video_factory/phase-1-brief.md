# Phase 1 Brief — `social_video_factory` skeleton + mock pipeline E2E

> This is the spec the Phase 1 implementation agent must satisfy. The overall design
> lives in `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read it first).
> This phase implements ONLY Phase 1. Do NOT build the browser layer, Hermes tools,
> or docs — later phases do those.

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater` (a fork of hermes-agent). Work directly in the repo, no worktree. Do not commit.

## Scope — new top-level package `social_video_factory/`

- `__init__.py`, `__main__.py` (delegates to cli).
- `config.py` — env-var config + path helpers. Use `python-dotenv` (`load_dotenv()`; core dep). Data root `.social_video_factory/` resolved from CWD, overridable via `SOCIAL_FACTORY_DATA_DIR`. Path helpers create dirs lazily: `jobs_dir()`, `profile_dir()`, `downloads_dir()`, `imported_dir()`, `rendered_dir()`, `state_dir()`, `logs_dir()`. Define ALL `SOCIAL_FACTORY_*` env vars from the master plan now (including browser + rate-limit ones) so later phases just read them; only Phase-1 paths use them this phase.
- `models.py` — `GenerationMode` and `JobStatus` (str, Enum) and provider markers exactly as the master plan lists. `Job` dataclass with `to_dict`/`from_dict` JSON round-trip. Fields (all of them, later phases need them): id, template, topic, generation_mode, target, status, provider, created_at, updated_at, idea, script, prompt, prompt_path, raw_media_path, imported_media_path, sidecar_path, rendered_path, captions(dict), review(dict), needs_human_reason, error, history(list of {status, ts, note}). `Job.advance(status, note=...)` appends history + bumps updated_at.
- `store.py` — `JobStore` atomic JSON persistence under `jobs_dir()` (`<job_id>.json`): `save`, `load`, `list_jobs(status=None, generation_mode=None)`, `exists`. Atomic = temp file + `os.replace`.
- `ideas.py`, `script.py`, `prompt_build.py` — deterministic templated creative stages (pure functions, str in/out). Commented TODO hook that a Hermes LLM could replace them later; DO NOT wire Hermes LLM now. No imports from `agent/` or `tools/`.
- `media.py` — `import_generated(job, src_path)`: verify ext in `{.mp4,.mov,.webm,.mkv,.m4v}`, probe with `ffprobe` (subprocess JSON), rename `SVF_<job_id>_<template>_raw.<ext>`, copy into `imported_dir()`, write metadata sidecar JSON. **ffprobe/ffmpeg are NOT installed in the dev env** — when missing/probe fails, record `probe_available=false` + `probe_error` and continue gracefully (never crash). `find_latest_download(downloads_dir)` returns newest video file (used later). Detect with `shutil.which("ffprobe")`.
- `render.py` — `render_9x16(job)` builds + runs ffmpeg → 1080x1920 MP4 with hook drawtext overlay, burned subtitles from the **script** (`build_srt(script_text, total_seconds)` pure helper, even timing), and a watermark. PURE helper `build_ffmpeg_command(input_path, srt_path, output_path, hook_text, watermark_text)` for unit tests. If ffmpeg missing, `render_9x16` does NOT crash the mock pipeline — see pipeline note.
- `captions.py` — `build_captions(job)` → `{"tiktok":..., "instagram":...}` (templated).
- `review.py` — `review(job)` → `{"accepted":bool,"reason":str,"backend":"mock"}` deterministic accept; TODO for VLM.
- `pipeline.py` — stage fns (`run_idea`, `run_script`, `run_prompt`, `save_prompt_file`, `run_import`, `run_review`, `run_render`, `run_captions`, `finalize_approval`) each `Job.advance` + persist via store. `create_job(template, topic, generation_mode, target="flow")` and `generate_one(...)`.
  - `mock`: synthesize a clip (ffmpeg `testsrc` if present; else write a tiny placeholder `.mp4`), then import → review → render → captions → status `awaiting_approval`. When ffmpeg absent, `run_render` SKIPS the encode (mark `rendered_path=None`, history note "render skipped: ffmpeg unavailable") so mock E2E completes. **Never auto-publish.**
  - `browser_flow`/`assisted_flow`/`flow_import`: `generate_one` runs idea→script→prompt→save_prompt_file then STOPS with a message to run the browser command (later phase).
  - `api_veo`: raise a clear "api_veo is disabled in this build" error.
- `cli.py` — `fire` CLI: `generate_one` (template, topic, generation_mode="mock", target="flow"), `list_jobs`, `show_job(job_id)`. End with `if __name__ == "__main__": fire.Fire(...)`. `python -m social_video_factory.cli generate-one --template dancing_cat --topic "x"` must work.

## Conventions
- `fire` CLI (see root `cli.py`, `batch_runner.py`). `from __future__ import annotations`, type hints, module docstrings explaining WHY. Match surrounding style.
- Phase 1 stays free of `agent/` and `tools/` imports (self-contained, testable without full hermes deps).
- Respect master-plan non-goals (no stealth/etc.) even though not directly relevant this phase.

## Tests — `tests/social_video_factory/` (+ `__init__.py`)
- config defaults + env overrides (monkeypatch + tmp `SOCIAL_FACTORY_DATA_DIR`).
- Job JSON round-trip + `advance` history.
- JobStore save/load/list (atomic) under tmp data dir.
- `build_srt` + `build_ffmpeg_command` pure: assert SRT timing splits; argv contains scale to 1080:1920, drawtext, subtitles, watermark.
- `media.find_latest_download` ordering.
- **Mock pipeline E2E**: `generate_one(generation_mode="mock", ...)` with tmp data dir → final status `awaiting_approval`, captions present, review accepted, completes **without real ffmpeg/ffprobe** (graceful path). Don't require ffmpeg mocking to pass.
- Every test sets `SOCIAL_FACTORY_DATA_DIR` to a tmp path (nothing writes into the repo).

## Environment / running
- System `python` on PATH is 3.14 (outside `requires-python` <3.14, lacks deps). **Use `uv` for everything**: `uv run pytest tests/social_video_factory/ -x -q` (uv provisions Python 3.12/3.13 + deps; `uv sync --extra dev` already completed). Don't use bare `python`.
- ffmpeg/ffprobe NOT installed here — tests MUST pass without them.
- `uv run ruff check social_video_factory/ tests/social_video_factory/` must be clean.

## Definition of done (report back explicitly)
1. All files above created.
2. `uv run pytest tests/social_video_factory/ -q` passes (paste summary line).
3. `uv run ruff check social_video_factory/ tests/social_video_factory/` clean (paste).
4. `uv run python -m social_video_factory.cli generate-one --template dancing_cat --topic "orange cat disco kitchen"` reaches `awaiting_approval` (use a throwaway tmp `SOCIAL_FACTORY_DATA_DIR`, then clean it up; paste output tail).
5. Concise signatures of public functions/classes per module (later phases build on them).
