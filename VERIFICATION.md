# Creation verification — 2026-10-17

Target: authenticated **deployed Hugging Face API**,
`https://q1232990-a-share-alpha-lab.hf.space`.
Space source/runtime: `136807d1481ab1639de5318d9ffb5abe3a9c4074`, RUNNING/READY.
One active simulation; no local evaluator or synthetic market data used for live checks.

- Full-model's supported live smoke: **80 PASS / 0 FAIL / 2 SKIP**. Admission fault
  injection is local-only; private-platform auth hides the app's own wrong-key 401.
- This client's doctor and paginated catalog query succeeded; all three documented
  scalar/TS/vector controls validated and completed on Train under the frozen Q5 profile.
- Full/summary reports, settings, run ids, definitions and compatibility agree.
  Saved three item CSVs, batch CSV and exact guide with SHA-256 checksums; collected
  recovery reopens locally without resubmission. Full run records remain ignored
  under `runs/hf-equipment-20261017/` in the creation checkout, not in the template.
- Signed-in editor Validate/Simulate worked. Eight displayed overall values and the
  run identity agree with the same deployed API result (default Q10, Train + validation).
- Offline client fault injection covers unknown intake, restart/410, GET-only recovery,
  readiness/capacity refusal, nulls, partial failures, report mismatches, unsafe links,
  redirects, credentials, corrupted evidence, budgets/OOS, writer locks and atomic writes.
  Those tests prove client behavior only. CI runs them without live credentials.

Compact [creation evidence](checks/creation_evidence.json) binds the controls, exports,
browser comparison and smoke counts to the runtime revision. Detailed logs and the TODO
review remain in the parent project's creation workspace; no full-model deployment was
changed. Re-run the controls for current acceptance rather than assuming this snapshot
proves a later deployment.

No alpha campaign was conducted. These known controls do not demonstrate an edge,
universal evaluator correctness or unattended-service reliability. The upstream read-only
source mount, continuous deployment acceptance, ≥60-minute soak and remaining data
assurance are still open. No TTL wait, restart/rollback or full source re-derivation
was performed. No template recipient inherits Space access or credentials.
