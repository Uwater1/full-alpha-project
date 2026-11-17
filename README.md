# full-alpha

Private **template**, not an alpha campaign. Choose **Use this template → Create a new
repository** on GitHub, clone your copy, then research there. The controls in `checks/`
verify infrastructure; their performance is not evidence of an alpha.

This Python 3.14 / uv client calls the deployed
[A-Share Alpha Lab](https://huggingface.co/spaces/q1232990/a-share-alpha-lab).
It contains no evaluator, raw data, strategy generator or automatic selector.
See the authoritative [API contract](https://github.com/Uwater1/a-share-alpha-lab/blob/main/API.md)
and [research guide](https://github.com/Uwater1/a-share-alpha-lab/blob/main/BRAIN_GUIDE.md).
Access to the private template does not grant access to the private Space.

## Setup and equipment check

Linux/macOS (local Unix file locking), Python 3.14, uv. Set credentials through your
shell/secret manager; `.env.example` documents names and is not auto-loaded.
Never put a token in commands, notebooks, candidates or tracked files.

```sh
uv sync --dev --locked
uv run ruff check .
uv run pytest -q
export ASHARE_BASE_URL=https://q1232990-a-share-alpha-lab.hf.space
# Supply HF_TOKEN securely: a read token with access to the private Space.
# Optional ASHARE_API_KEY goes in X-API-Key when the server requires it.
uv run full-alpha doctor --out runs/environment.json
uv run full-alpha catalog fields --search gap --offset 0 --limit 20
uv run full-alpha validate --protocol checks/protocol.toml --candidates checks/smoke.csv
uv run full-alpha run --protocol checks/protocol.toml --candidates checks/smoke.csv --run-dir runs/equipment-check
uv run full-alpha resume --run-dir runs/equipment-check
```

`doctor` reads health, readiness, metadata and limits without submitting work. It
fails unless READY; optional dependencies can still fail when requested.
`catalog` returns one page; advance `--offset` until the reported total is exhausted.
Validation proves formula/settings eligibility only.
`run` explicitly submits one bounded batch (up to 16 labelled contenders), saves
its job id before polling, compares full and summary reports/settings/identity,
and saves recorded CSV bytes and the exact guide. Jobs execute serially on the server.
Request and polling timeouts are finite. A polling timeout leaves a resumable job.

## Research in your generated repository

1. Create a tracked study directory with `protocol.toml` and `candidates.csv`.
   Start from the control files, change `purpose` to `research`, state one hypothesis,
   acceptance/falsification conditions, **all known prior search**, a fixed candidate
   budget, period and settings. Keep rejected and failed contenders. Unknown prior
   history must be labelled unknown. Budget enforcement covers this batch only;
   maintain your campaign-wide attempt ledger and count every new batch.
2. Use Train for exploration. Freeze the shortlist and acceptance rules before
   a bounded Validation check; repeated Validation use is tuning, not untouched
   confirmation. OOS beginning 2023-01-01 is sealed and cannot be requested.
3. Validate against the live registries, then submit once into a new run directory.
   The directory freezes the actual payload and protocol before intake. Record
   costs/settings from the result; never infer that omitted overrides mean zero costs.
4. Inspect every result/error and recorded provenance/coverage. Save meaningful
   runs in your generated repository by explicitly adding them (`runs/` is ignored
   to prevent accidental publication of exploratory output). Keep protocol, engine/
   data pins, all attempts, null metrics, errors and checksums together.

No acceptance threshold or multiple-testing correction is invented here. Add
walk-forward, correlation/turnover/cost robustness and selection gates only for
a declared study. A completed job does not establish profitability. `Net Sharpe`
and Research Fitness retain the engine definitions; gross-spread Win %/Max DD %
are diagnostics, not executed NAV metrics. HAC t-values are not multiple-testing
adjusted. No automatic promotion or trading exists.

## Run records and recovery

| File | Meaning |
|---|---|
| `manifest.json` | Frozen payload, study, origin and client version; checksum bound to state. |
| `state.json` | Key saved before submission; accepted job/instance saved before polling. No credentials. |
| `environment.json`, `validation.json`, `accepted.json`, `status.json` | Live metadata and recorded control responses; includes refusal evidence. |
| `summary.json` | Recorded compact results, settings, identities and all contender errors. |
| `batch.csv`, `NN-candidate.csv`, `guide.csv` | Exact server download bytes; no recomputation or rounding. |
| `files.json` | SHA-256, source-relative link and server filename for each download. Local names are safe aliases. |

JSON files are internal control/evidence records. Analysis downloads remain CSV.
`resume` is GET-only for a known job; fully collected records verify checksums and
open offline even after the job expires. Do not edit a run's manifest or state.
Hashes detect accidental changes; they are not cryptographic attestations against
someone who can rewrite all local evidence.

If a submission response is lost before the job id is saved, the client stops with
`phase=submitting`: the outcome is unknown. It deliberately does **not** retry POST,
even using the saved key, because a restart between instance checks can create new
work. Reconcile with the operator; explicitly declare any new intake in a fresh run.
Do not delete the uncertain attempt. This is the client's conservative recovery policy.
On `410 JOB_GONE`, preserve evidence and explicitly decide whether a new attempt is
warranted. On 429, authentication failure or malformed responses, inspect state and
server limits; no automatic retry storm. Never cancel another user's job.
One process can own a run directory at a time. Local atomic writes handle process
interruption; keep evidence on reliable local storage, not remote bucket mounts.

CI runs only offline HTTP fault injection; it never receives a token, submits live
work or creates alpha evidence. Live acceptance is a separate operator action.
See [verification](VERIFICATION.md) for the target and boundaries checked at creation.
