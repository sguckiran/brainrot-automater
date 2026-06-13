# Audit log — `social_video_factory` phased build

Each phase is implemented by a dedicated agent against its `phase-N-brief.md`, then
audited here by the orchestrator (re-running tests/lint independently and reading the code).

## Phase 1 — skeleton + mock pipeline E2E — ✅ PASS (2026-06-13)

Audited against `phase-1-brief.md`.

- **Files**: all required modules present (`config, models, store, ideas, script, prompt_build, media, render, captions, review, pipeline, cli, __init__, __main__`) + tests (`test_config/models/store/render/media/pipeline`).
- **Independent pytest**: `30 passed`.
- **Independent ruff**: clean.
- **Independent CLI smoke** (tmp data dir): `generate-one` reaches `awaiting_approval`; artifacts written: job JSON, saved prompt, mock src, imported clip + sidecar JSON, SRT (no MP4 — ffmpeg absent → correct graceful skip).
- **Brief compliance**: config has all `SOCIAL_FACTORY_*` env vars + correct defaults (headless=false, 3/20/180/10); `Job` model carries all later-phase fields + `advance` history; `render.build_ffmpeg_command` pure & correct (scale/pad 1080x1920, subtitles, drawtext hook + watermark, Windows path escaping); `media` graceful ffprobe degradation + canonical rename + sidecar; pipeline `mock` full / prompt-only stop / `api_veo` disabled; no `agent/` or `tools/` imports; no auto-publish path.
- **Nits (non-blocking)**: mock source clip is written under `media/browser_downloads/` (semantically it's not a browser download, but harmless); `pyproject`/`packages.find` wiring deferred to Phase 6 per the master plan.

Verdict: accepted, proceed to Phase 2.

## Phase 2 — browser controller + selectors + browser-login — ✅ PASS (2026-06-13)

Audited against `phase-2-brief.md`.

- **Files**: `browser/{__init__,controller,selectors}.py`, `browser_selectors.example.yaml`, `cli.py` (`browser-login`), `tools/lazy_deps.py` (+`"social_video_factory.browser": ("playwright==1.60.0",)`), `.gitignore` (+`.social_video_factory/`), `.env.example` (full `SOCIAL_FACTORY_*` block), tests `test_browser_controller.py` + `test_selectors.py`.
- **Independent pytest**: `45 passed` (Phase 1 still green). **ruff**: clean.
- **Safety**: `controller.py` launch passes NO `args=`; all stealth-token matches are in comments/docstrings documenting deliberate omission. `launch_persistent_context` with persistent profile dir, headed default, downloads configured. Lazy Playwright import only in `start()` → `BrowserUnavailable` with `pip install playwright` + `python -m playwright install chromium` remediation. `NullController` fallback clean.
- **Selectors**: layered resolution (configured CSS → role/label → text → manual_pause), pure/duck-typed (tested with fakes, no real Playwright). Example YAML has both `flow`/`gemini` with all 6 action keys + all 11 `hard_stops` pattern keys.
- **CLI**: `browser-login` resolves URL from `--url`/env, exits 2 if unset, exits 1 + remediation on `BrowserUnavailable`, `finally: close()`.
- **Deviations (sound)**: stealth test tokenizes out comments before grepping (substring grep would false-positive on the safety docstring); lazy import kept inside `start()` to preserve "importable without Hermes tree"; pyproject/uv.lock deferred to Phase 6 per brief.

Verdict: accepted, proceed to Phase 3.

## Phase 3 — browser worker + hard stops + rate limiting — ✅ PASS (2026-06-13)

Audited against `phase-3-brief.md`.

- **Files**: `browser/{hard_stops,artifacts,worker}.py`, `rate_limit.py`, `browser/__init__.py` (exports), `cli.py` (`browser-generate`), tests `test_hard_stops/test_rate_limit/test_artifacts/test_worker`.
- **Independent pytest**: `83 passed`. **ruff**: clean.
- **Worker safety contract verified by reading `worker.py`**: rate gate runs FIRST before controller is even wired/opened; `needs_human_confirm` honored; URL resolved before open; hard-stop re-check after nav, after submit, and every poll iteration; manual-pause fallback on every selector miss (prompt/submit/wait/download); `record()` only after a verified video download (never on a hard stop); `finally: close()` idempotent; continues via Phase-1 stages; no auto-publish.
- **Redaction (`artifacts.py`)**: scrubs key=value secret pairs, `Bearer` tokens, JWT-ish opaque blobs; strips `<script>` from HTML snapshots; redacts `note` + `selector_used`; best-effort (never breaks flow).
- **`rate_limit.py`**: atomic write, 24h prune, hourly/daily/min-gap denials, confirm cadence, corrupt-file tolerance, injectable clock/confirm.
- **Observations for Phase 6 (non-blocking)**:
  1. `hard_stops` `consent_policy_modal` defaults (`"we use cookies"`, `"i agree"`, `"accept all"`) scanned against full `html()` will likely fire on nearly every Google cookie banner → frequent `needs_human`. Conservative-by-design (matches the brief), but consider matching VISIBLE text and/or trimming the broadest consent phrases.
  2. Rate-limited and confirm-declined paths add a `GENERATING` history note; confirm-declined returns a `needs_human` outcome WITHOUT setting `JobStatus.NEEDS_HUMAN`/`needs_human_reason` on the persisted job (minor inconsistency).
  3. `needs_human_confirm` fires on the very first generation (`total_count==0`). Arguably a desirable pre-flight checkpoint; flag if undesired.

Verdict: accepted, proceed to Phase 4.

## Phase 4 — queue mode + manual recovery — ✅ PASS (2026-06-13)

Audited against `phase-4-brief.md`.

- **Files**: `browser/queue.py` (`run_queue`, `QueueResult`), `pipeline.py` (+`finish_after_import`), `browser/worker.py` (tail refactored to `run_import` + `finish_after_import` — behavior-preserving, Phase-3 tests still green), `cli.py` (`browser-run-queue`, `import-latest-browser-download`, both registered), `browser/__init__.py` exports, tests `test_queue/test_import_latest`.
- **Independent pytest**: `92 passed`. **ruff**: clean.
- **`queue.py`**: selects only pending `browser_flow` jobs (`{created,idea,scripted,prompted}`), oldest-first, capped at limit; prepares missing prompts; pauses (`sleep`) only between successes; STOPS on `needs_human`/`error`/`rate_limited` recording `stopped_reason`; all injectable.
- **CLI smoke (no FLOW_URL)**: `browser-run-queue` processed 1 job, stopped cleanly, exit 0; `import-latest` with empty downloads printed the no-download message (exit 5 via SystemExit; pipe masked `$?` in the smoke harness but unit test asserts it).
- **🔴 ESCALATED DEFECT (fix in Phase 6)**: the smoke run stopped with `needs_human: human confirm declined` on the FIRST job. Root cause: `RateLimiter.check()` sets `needs_human_confirm` when `total_count % require_human_confirm_every == 0`, which is True at `total_count==0`; the default `input()` confirm raises EOFError in non-interactive contexts → returns False. Net effect: **automated `browser-generate`/`browser-run-queue` can never start a generation in a non-TTY**. Required fix: change cadence to `confirm_every > 0 and total_count > 0 and total_count % confirm_every == 0` (checkpoint before the 11th/21st/... generation, not the 1st). Consider also: confirm-declined should set `JobStatus.NEEDS_HUMAN` + `needs_human_reason` for consistency.

Verdict: accepted, proceed to Phase 5 (and fold the confirm-cadence fix into Phase 6).

## Phase 5 — Hermes tools registration — ✅ PASS (2026-06-13)

Audited against `phase-5-brief.md`.

- **Files**: `tools/social_video_factory_tool.py` (4 tools), `tests/social_video_factory/test_hermes_tools.py` (10 tests). No Phase 1–4 files modified (verified via git status).
- **Independent pytest**: `102 passed`. **ruff**: clean.
- **Discovery verified**: `discover_builtin_tools()` registers all 4 names under toolset `social_video_factory`; `check_fn` (`_svf_available`) returns True; schemas carry safety-posture descriptions.
- **Non-interactive safety (read the module)**: `_NonBlockingController.wait_for_enter` is a real method (so `__getattr__` cannot shadow it) that logs + returns without reading stdin; all other attrs delegate to the real controller; `_non_interactive_rate_limiter()` injects `confirm=lambda _:False`; the queue tool injects a non-interactive `generate` closure. Login tool is guidance-only (returns command + resolved URL + `profile_exists`), never opens a browser, never claims to bypass login. Handlers return `tool_error` JSON on missing job / no download / `BrowserUnavailable`.
- **Deviation (correct)**: used 4 literal top-level `registry.register(...)` calls (not a helper wrapper) because `discover_builtin_tools` AST-matches that exact call shape.

Verdict: accepted, proceed to Phase 6.

## Phase 6 — docs + packaging + required fixes + final verification — ✅ PASS (2026-06-13)

Audited against `phase-6-brief.md`.

- **Fix 1 (confirm cadence)**: `rate_limit.py` now gates `needs_human_confirm` on `total_count > 0` → first automated generation no longer auto-declines. **Verified live**: `browser-run-queue` on a fresh state now proceeds past the confirm gate and stops at "no URL configured" (the real next step) instead of "human confirm declined". Defect closed.
- **Fix 2 (confirm-declined consistency)**: `worker.py` declined branch now sets `needs_human_reason` + advances to `JobStatus.NEEDS_HUMAN`. Test extended.
- **Packaging**: `pyproject.toml` diff is EXACTLY the two allowed edits — `package-data` `social_video_factory = ["*.yaml"]` + `packages.find.include` additions. `uv.lock` confirmed untouched (no dependency/extra added; Playwright stays in `lazy_deps`). Env still resolves; package-data sanity passes.
- **Docs**: `website/docs/user-guide/features/browser-assisted-gemini-flow.md` created; front-matter matches sibling `image-generation.md` (`title`/`description`/`sidebar_label`/`sidebar_position: 8`); features index is generated-index so no sidebar edit needed. Covers logged-in profile, no API billing, selector layers + `SOCIAL_FACTORY_SELECTORS_FILE`, won't-bypass posture, rate-limit env table, all CLI commands, full env table, the 4 Hermes tools (login = guidance only), "What it will NOT do" section, Playwright lazy-install + `playwright install chromium`.
- **Final verification (independent)**: `102 passed`; ruff clean; 4 tools discovered; mock E2E → `awaiting_approval`. `ty` shows 1 expected diagnostic (lazy `playwright.sync_api` import, guarded by try/except — by design).

Verdict: accepted. **All 6 phases complete.**

---

## Outstanding (optional, non-blocking) follow-ups
- `hard_stops` `consent_policy_modal` defaults (`"we use cookies"`, `"i agree"`, `"accept all"`) scanned over full `html()` may false-positive on Google cookie banners → premature `needs_human`. Consider matching visible text and/or trimming the broadest consent phrases against the live UI.
- The bundled `browser_selectors.example.yaml` selectors are deliberate placeholders; they must be tuned against the live Flow/Gemini UI (expected — the layered resolver + manual pause cover the gap meanwhile).
- Feature is entirely uncommitted (no commit was requested); `.env.example`, `.gitignore`, `tools/lazy_deps.py`, `pyproject.toml` are modified, the rest are new untracked files.
