Baseline: `baseline` (git None, seed 42) · PoC: `poc` (git None, seed 42)

| Metric (unit) | Slice | Baseline | PoC | Δ abs | Δ rel | Better | N |
|---|---|---|---|---|---|---|---|
| **Defect Recall@B** (GT defects in top-B / GT defects) | all | 0.4500 | 0.9000 | 0.4500 | +100.0% | higher | 56 |
| Precision@B (GT defects in top-B / B) | all | 0.4500 | 0.9000 | 0.4500 | +100.0% | higher | 56 |
| False alarm in top-B (clean images in top-B / clean images) | light=day | 0.1500 | 0.0500 | -0.1000 | -66.7% | lower | 24 |
| False alarm in top-B (clean images in top-B / clean images) | light=dusk | 0.2500 | 0.0625 | -0.1875 | -75.0% | lower | 16 |
| False alarm in top-B (clean images in top-B / clean images) | light=night | 0.6250 | 0.0625 | -0.5625 | -90.0% | lower | 16 |
| Runtime / 100 items (s) | all | 0.0905 | 0.5084 | | | lower | |
