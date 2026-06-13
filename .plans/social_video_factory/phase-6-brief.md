# Phase 6 Brief — docs + packaging + required fixes + final verification

> Master design: `C:\Users\sinan\.claude\plans\lucky-strolling-lake.md` (read first).
> Phases 1–5 are DONE and audited. This phase: a required correctness fix surfaced in audit, packaging config (NO dependency changes), the user docs, and a full final verification pass.

Repo: `C:\Users\sinan\IdeaProjects\coursework\brainrot-automater`. In-repo, no worktree, no commit. `uv run` for pytest/ruff. No real browser/Playwright/network in tests.

## 1. REQUIRED FIX — human-confirm cadence (audit escalation)
In `social_video_factory/rate_limit.py`, `RateLimiter.check()` currently sets:
```
needs_confirm = confirm_every > 0 and (total_count % confirm_every == 0)
```
This is True at `total_count == 0`, so the FIRST generation always requires a human confirm; combined with the default `input()` confirm raising EOFError in non-interactive contexts → returns False → **every automated `browser-generate` / `browser-run-queue` immediately declines and can never start**. Verified live in Phase 4 smoke (`needs_human: human confirm declined` on the first job).
- **Fix**: `needs_confirm = confirm_every > 0 and total_count > 0 and (total_count % confirm_every == 0)`. So no confirm before the 1st…Nth generation; the checkpoint falls before the (N+1)th, (2N+1)th, … generation. Update the module docstring/comment accordingly.
- **Tests**: update/add in `test_rate_limit.py` — assert the FIRST `check()` (fresh state, `total_count==0`) has `needs_human_confirm is False`; after `confirm_every` recorded generations, the next `check()` has `needs_human_confirm is True`. Fix any existing test that asserted confirm at count 0.

## 2. SMALL CONSISTENCY FIX — confirm-declined outcome (audit observation #2)
In `social_video_factory/browser/worker.py`, the human-confirm-declined branch returns a `needs_human` `GenerationOutcome` but leaves the persisted job in `GENERATING` without `needs_human_reason`. Make it consistent with every other `needs_human` exit: set `job.needs_human_reason` and `job.advance(JobStatus.NEEDS_HUMAN, note=reason)` before returning (do NOT open/record). Keep the rate-limited branch as-is (rate_limited is not needs_human). Add/extend a worker test asserting the declined path leaves `job.status == JobStatus.NEEDS_HUMAN.value` and sets `needs_human_reason`. Do not regress other worker/queue tests.

## 3. PACKAGING (config only — NO dependency/lockfile changes)
Goal: make the package installable + ship the bundled selectors YAML, WITHOUT changing any dependency (so `uv.lock` is NOT touched and the lockfile-check CI cannot break). Playwright stays installed via `tools/lazy_deps.py` (already wired in Phase 2) — do NOT add a Playwright extra/dependency to `pyproject.toml`.
- `pyproject.toml` → `[tool.setuptools.packages.find].include` (around line 322): add `"social_video_factory"` and `"social_video_factory.*"` to the list.
- `pyproject.toml` → `[tool.setuptools.package-data]` (around line 303): add an entry so the bundled selectors file ships in the wheel, e.g. `"social_video_factory" = ["*.yaml"]` (match the existing section's formatting/quoting style). This matters because `selectors.py` loads `browser_selectors.example.yaml` from the installed package dir.
- Do NOT run `uv lock`. Do NOT add to `[project.dependencies]` or `[project.optional-dependencies]`. After editing, confirm the env is unaffected: `uv run python -c "import social_video_factory, social_video_factory.cli"` and `uv run pytest tests/social_video_factory/ -q` both succeed.
- Verify the example YAML is reachable as package data (sanity: `uv run python -c "from social_video_factory.browser.selectors import load_selector_config as L; print(sorted(L().keys()))"`).

## 4. DOCS — "Browser-assisted Gemini/Flow mode"
Create `website/docs/user-guide/features/browser-assisted-gemini-flow.md`. FIRST inspect a sibling doc in `website/docs/user-guide/features/` to copy the exact front-matter convention (e.g. `sidebar_position`, `title`, any `id`) and heading style — match it. Content must cover (from the master plan):
- It uses YOUR logged-in Chromium profile (persistent profile dir) and your existing Gemini/Flow/Omni subscription.
- It AVOIDS Gemini API calls (no Veo/API billing).
- It is LESS STABLE than API mode because web UIs change — and how to fix that: edit `social_video_factory/browser_selectors.example.yaml` (or point `SOCIAL_FACTORY_SELECTORS_FILE` at your own copy); selectors are tried in layers (configured → accessible role/label → visible text → manual pause).
- It MUST respect account limits and website prompts; it will NOT bypass CAPTCHA, login, rate limits, or safety refusals — on any such screen it stops, screenshots, and marks the job `needs_human`.
- Local conservative rate limits (the `SOCIAL_FACTORY_BROWSER_MAX_*` / `MIN_SECONDS_BETWEEN` / `REQUIRE_HUMAN_CONFIRM_EVERY` env vars) are always enforced even if the site would allow more.
- Setup + usage commands:
  - First run: `python -m social_video_factory.cli browser-login`
  - Generate: `python -m social_video_factory.cli generate-one --template dancing_cat --topic "orange cat disco kitchen" --generation-mode browser_flow` then `python -m social_video_factory.cli browser-generate --job-id <job_id>`
  - Queue: `python -m social_video_factory.cli browser-run-queue --limit 5`
  - Manual recovery: `python -m social_video_factory.cli import-latest-browser-download --job-id <job_id>`
- The relevant env vars (table) with defaults.
- The 4 Hermes tools (names + one-line each) and the note that the login tool only returns guidance (login is manual).
- A short "What it will NOT do" safety section (no stealth/anti-detection, no CAPTCHA solving, no proxy/account rotation, no usage-limit bypass, no scraping/engagement automation, no auto-publish; secrets never logged).
- Note Playwright is required and is lazy-installed on first browser use; the Chromium binary needs `python -m playwright install chromium`.
- If the features section has an index/sidebar list that must be updated for the page to appear, update it (check for a `_category_.json` or sidebar config in that folder and mirror how other feature docs are listed).

## 5. FINAL VERIFICATION (run + paste results)
- `uv run pytest tests/social_video_factory/ -q` — all green (paste summary; note the new count).
- `uv run ruff check social_video_factory/ tools/social_video_factory_tool.py tests/social_video_factory/` — clean.
- Tool discovery still works: `uv run python -c "from tools.registry import registry, discover_builtin_tools; discover_builtin_tools(); print(sorted(n for n in registry.get_all_tool_names() if 'social_video_factory' in n))"` → 4 names.
- Mock E2E still works end-to-end: `uv run python -m social_video_factory.cli generate-one --template dancing_cat --topic "orange cat disco kitchen"` (use a tmp `SOCIAL_FACTORY_DATA_DIR`, clean up) → reaches `awaiting_approval`.
- If a repo typechecker is quick to run on just the new files (the dev extra pins `ty`), run `uv run ty check social_video_factory/ tools/social_video_factory_tool.py` and report; if it surfaces pre-existing-style noise unrelated to our code, summarize rather than chase it.
- Confirm (git status) that NO Phase 1–5 behavior files were changed except the two required fixes in `rate_limit.py` and `worker.py`, plus `pyproject.toml` and the new docs file.

## Definition of done (report back explicitly)
1. The two fixes applied (cadence + confirm-declined consistency) with tests.
2. Packaging config edits done; `uv.lock` NOT modified; env still resolves (paste the import + pytest confirmation).
3. Docs page created (+ any sidebar/category update); paste its path and front-matter.
4. Final verification commands + their output (pytest summary, ruff, discovery 4 names, mock E2E status, typecheck note).
5. `git status --porcelain` listing so the full change set is visible.
6. Any deviations and why.
