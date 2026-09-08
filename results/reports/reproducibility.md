# Reproducibility verification

Generated 2026-09-08T05:11:41+00:00 from IndicPass v0.1.0 at `8a09173ef351`.

Every pipeline was run **twice, in two separate processes**, each writing to its own directory. The two reports were then compared byte for byte after removing the keys below and nothing else.

Excluded from the comparison: `generated_at`, `reproducibility`.

| milestone | experiment | report | identical | canonical SHA-256 |
| --- | --- | --- | --- | --- |
| M2 | `coverage` | `indicdict_coverage_hin` | yes | `06366a6d7c8a8b14...` |
| M2 | `benchmark` | `password_benchmark_hin` | yes | `65fb95a5f2767705...` |
|  |  | `mined_tier_ablation` | yes | `44f64f0672511ac6...` |
|  |  | `guess_model_sensitivity` | yes | `ab5905b88b7637f7...` |
| M3 | `pcfg` | `pcfg_benchmark_hin` | yes | `22ec6cd0b3b2f37d...` |
|  |  | `pcfg_targeted_hin` | yes | `b14a55af21273336...` |
| M4 | `reference_attack` | `reference_attack_hin` | yes | `d2281449da676cb0...` |
| M5 | `oov_attack` | `milestone5_oov_attack` | yes | `d1e94bfefe944939...` |

| experiment | wall clock (two runs) |
| --- | ---: |
| `coverage` | 10s |
| `benchmark` | 103s |
| `pcfg` | 466s |
| `reference_attack` | 129s |
| `oov_attack` | 530s |

**8 of 8 reports are byte-identical across two processes.** 0 could not be separated into two directories and are noted as such.

Full SHA-256 digests:

```
indicdict_coverage_hin           sha256:06366a6d7c8a8b140ec5bba7475be83d6a2506bb361a6254865a0602ea2f601f
password_benchmark_hin           sha256:65fb95a5f27677051377d6882149b6c1ab7b66f623db5dbb0473117719b5de97
mined_tier_ablation              sha256:44f64f0672511ac6e49b1314c041150a81db1f19af99fe340cbf584c87a8acf2
guess_model_sensitivity          sha256:ab5905b88b7637f7b784c4bcc8ce6c8192be9b3d3f25ed4d72c75c1215f54c20
pcfg_benchmark_hin               sha256:22ec6cd0b3b2f37d8e59f445631e6996cb3a1a409ff7102d6ff038cb333bf020
pcfg_targeted_hin                sha256:b14a55af21273336b8b63b96997f718dbbf4a0828c22ff4a83f42e01d51dff17
reference_attack_hin             sha256:d2281449da676cb07de6b521aa1f4cfa7822c3c1e4766a2ece414a3a21f0beae
milestone5_oov_attack            sha256:d1e94bfefe9449390eeb7f062bae6f976a7c86b5890730f3d1b83b41bfd7b2b7
```

These are digests of the **canonical payload** -- the report JSON with the volatile keys removed and the remaining keys sorted -- not of the file on disk, which carries a timestamp. Recompute one with:

```bash
python scripts/verify_reproducibility.py --languages hin
```

