# Judge calibration runner (FP-EVAL-004)

The v2 runner accepts only a real Acceptance Observation Bundle. Each eligible
functional sample must carry semantic Judge rubrics, a non-empty observed
product output, its SHA-256 digest, passed deterministic assertions, and
evidence files whose hashes can be recomputed. Case input and `expected` data
are never candidate output or reference labels. Safety/fault cases and failed
deterministic gates are excluded.

```powershell
python evals/runners/calibrate_judge.py build-blind-set `
  --observations artifacts/acceptance/<run>/judge-observations.v1.json `
  --evidence-root artifacts/acceptance/<run> `
  --out-dir artifacts/acceptance/<run>/judge-calibration

python evals/runners/calibrate_judge.py calibrate `
  --blind artifacts/acceptance/<run>/judge-calibration/blind-set.v2.json `
  --bindings artifacts/acceptance/<run>/judge-calibration/blind-set-bindings.v2.json `
  --human-round-1 human-round-1.json --human-round-2 human-round-2.json `
  --adjudication adjudication.json --judge-predictions judge-predictions.json `
  --out calibration.v2.json
```

Human reviews use distinct, nonempty reviewer identities and cover the Blind
Set exactly. Every
disagreement needs an explicit adjudication. Judge predictions are a separate
file and must bind a model ID and Prompt SHA-256. Missing inputs, fewer than 30
trusted samples, human or Judge kappa below 0.75, and any proxy backend produce
`USER_GATE_REQUIRED` with `aggregation_effect=no_effect`. A passing metric
result is only `status=candidate` and also has no aggregation effect. Release
use requires a `flowpilot.judge-calibration-freeze.v2` record with an S1
approval identity and exact hashes of every calibration input and output.
Synthetic fixtures are never themselves release-effective.

The committed `blind-set.v1.json`, `blind-set-labels.v1.json`, review sheet,
verdict template and `calibration.json` are historical placeholders generated
from Dataset Case inputs/expected values. The v2 `verify` command rejects them;
they cannot support Acceptance aggregation or a Judge-calibrated claim.
