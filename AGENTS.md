# full-alpha agent guide

- This is a reusable client template. Do research in repositories generated from it.
  `checks/` holds infrastructure controls, never alpha contenders or selection evidence.
- Use Python 3.14 and uv. Read README and the live `/api/v1/meta`/registries before work.
- All simulations use full-model's supported HTTP API. Never fork evaluator semantics,
  hydrate source data locally, invent fields/metrics, or access sealed OOS.
- Freeze hypothesis, budget, settings, prior search and acceptance before intake.
  Retain failed/unknown attempts and distinguish Train exploration from Validation reuse.
- Persist key/payload before POST and job id before polling. Resume known jobs with GET.
  Unknown intake, restart or 410 never authorizes automatic new submission.
- Only same-origin `/api/v1/` links may receive credentials. No redirects; no logged tokens.
  Export exact recorded CSVs, including `guide.csv`; keep nulls and native definitions.
- One local writer per run directory. Never alter old manifests/evidence to fit new work.
- Keep `TODO.md` unfinished-only. No speculative search, ranking, parallelism or trading.
- Verify client changes with `uv sync --dev --locked`, `uv run ruff check .`,
  `uv run pytest -q`; run declared controls against Hugging Face for live acceptance.
  Offline mocks establish client behavior, not correctness of the deployed evaluator.
