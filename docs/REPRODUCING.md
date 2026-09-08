# Reproducing IndicPass

Everything needed to regenerate every number in `results/reports/final_report.md`
from a clean checkout, and the hashes to check the result against.

Two things are **not** in the repository and cannot be: the raw Aksharantar
corpus (gigabytes, fetched from Hugging Face) and the trained transliteration
model (checkpoint weights). Everything downstream of them is either committed or
regenerated deterministically from what is committed, and §4 says exactly which
steps need which.

---

## 1. Environment

| | |
| --- | --- |
| Python | 3.14.3 (project requires >= 3.10) |
| OS the reported numbers were produced on | Windows 11 (26100), x86-64 |
| OS assumptions | none material — no path, encoding or line-ending behaviour affects a reported number. Reports are written UTF-8 with explicit encoding; the guess model is pure Python arithmetic |
| Hardware | none material for §4 steps 2–8. Only the dictionary build (step 1) benefits from a GPU |

Runtime dependencies, all pinned by minimum version in `requirements/base.txt`
and installed at these versions for the reported run:

| package | version | why it is required |
| --- | --- | --- |
| PyYAML | 6.0.3 | reads `config/*.yaml` |
| python-dotenv | 1.2.3 | reads `.env` for `HF_TOKEN` |
| huggingface-hub | 0.27+ | dataset download only |
| pyarrow | 25.0.1 | reads parquet shards |
| tqdm | 4.70.0 | progress |
| rich | 15.0.0 | console output |
| **zxcvbn** | **4.5.0** | **the baseline estimator. Without it no comparative claim can be made, so it is a hard requirement rather than an extra** |
| **wordfreq** | **3.1.1** | **the external frequency table. Build-time only — the values are baked into the committed dictionary, so scoring never needs it** |

Development extras (`requirements/dev.txt`): pytest 9.1.1, ruff 0.16.5, black
26.5.1, mypy 2.3.1.

Training extras (`requirements/ml.txt`, needed only for step 1): torch 2.14.0,
numpy 2.5.2.

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements/dev.txt
```

The package is **not** installed into the environment for the reported run.
`scripts/*.py` put `src/` on `sys.path` via `scripts/_bootstrap.py`, and pytest
does the same through `pythonpath` in `pyproject.toml`. `pip install -e .` also
works and changes nothing.

---

## 2. Configuration and seeds

Every number the engine uses lives in `config/password.yaml`; nothing under
`src/indicpass/password/` hardcodes a threshold, a cost or a path. The seeds
that matter:

| seed | where | what it controls |
| --- | --- | --- |
| 42 | `evaluation.seed` | the 1,400-sample benchmark corpus |
| 42 | `pcfg.estimator.sample_seed` | M3's guess-curve sampling |
| 42 | `reference_attack.seed` | M4's wordlist shuffle for unranked entries |
| 42 | `character_attack.training_seed` | M5's hold-out arm |
| 42 | `character_attack.bootstrap.seed` | M5's bootstrap resampling |

The benchmark corpus is **generated, not stored**. Regenerating from seed 42
reproduces it exactly, which is what reproducibility requires; storing 1,400
plausible Indic passwords would be publishing a cracking wordlist.

---

## 3. Committed artefacts and their hashes

| artefact | committed? | SHA-256 |
| --- | --- | --- |
| `data/dictionaries/indicdict_hin.jsonl` (297,747 entries, ~100 MB) | **no** — gitignored build artefact | `2a91a9f3c8fb699277fab68905bb94476d410c765fae15461e4d38f655aa6642` |
| `data/dictionaries/indicdict_hin.meta.json` | yes — the provenance record | see file |
| `data/pcfg/pcfg_hin.json` (47 KiB: the guess curve, not the grammar) | yes | `189b32a765f313f230da5e73cba47135974420985157155951f40fa858dc0827` |
| benchmark corpus (1,400 samples, seed 42) | no — regenerated | `2356a7d602926706fc7ed0d67884d7c1c9f8e4e57b456d00dc3bdbcb1a8edd6a` |
| M5 attack fingerprint | in the report | `0166a4f715559362431d01a4088df7e42ba83147f181dcb7ab0db84789c8a435` |
| M5 character model fingerprint | in the report | `ab07531bd53c40870fbdea88e737fd63d9bf19b9468344cb433c827e7343224f` |

The dictionary is 100 MB and is a deterministic build artefact, so it is
gitignored while its `.meta.json` sidecar — tier sizes, filters, the model that
produced the native forms, the frequency source — is committed. **Every guess
estimate depends on those tier sizes**, which is why the sidecar is kept even
though the data is not.

The PCFG artefact carries a fingerprint over `(spelling, frequency, tier)`. A
grammar trained against a different dictionary is **refused at load time**
rather than silently producing wrong numbers.

---

## 4. Commands

Steps 2–8 need neither torch nor a network.

```bash
# 1. The dictionary. ~35 min on CPU; needs torch and the preprocessed corpus.
#    SKIP THIS if data/dictionaries/indicdict_hin.jsonl is already present.
python scripts/build_indicdict.py --languages hin

# 2. M1/M2 -- dictionary coverage against the curated probe set
python scripts/indicdict_coverage.py --languages hin

# 3. M2 -- benchmark, mined-tier ablation and guess-model sensitivity,
#    from one scoring pass                                        (~85 s)
python scripts/password_benchmark.py --languages hin

# 4. M3 -- fit the grammar and sample the guess curve             (~20 s)
python scripts/train_pcfg.py --languages hin

# 5. M3 -- evaluate it: same 1,400 samples, twelve ablation arms,
#    targeted cases, random control                               (~160 s)
python scripts/pcfg_benchmark.py --languages hin

# 6. M4 -- the wordlist reference attack, six arms                (~24 s)
python scripts/reference_attack.py --languages hin

# 7. M5 -- the out-of-lexicon character attack, seven arms, bootstrap
#    intervals, and its own second-process byte-identity check    (~5 min)
python scripts/milestone5_oov_attack.py --languages hin

# 8. Determinism: every pipeline above run twice in separate processes
#    and compared byte for byte                                   (~13 min)
python scripts/verify_reproducibility.py --languages hin

# 9. The final report and its figures
python scripts/final_report.py

# 10. Quality gates
python -m pytest
python -m ruff check .
```

Steps 6, 7 and 8 **build no wordlist of any kind**. Both attacks count their
enumerations and invert them arithmetically; no cracking wordlist exists at any
point in this pipeline.

---

## 5. Expected results

### Tests

```
785 passed
```

### Lint

`python -m ruff check .` reports **35 pre-existing errors in 10 files**, none of
them in the password engine. They are stylistic rules that ruff 0.16.5 applies
more strictly than the version the files were last linted with (`UP035`
`typing.Iterable` → `collections.abc`, `UP037` quoted annotations, `RUF100`
unused `noqa`, `I001` import order, plus a few long lines). The exact files:

```
scripts/download_datasets.py    scripts/export_bundle.py
scripts/inspect_dataset.py      scripts/preprocess_dataset.py
scripts/validate_dataset.py     src/indicpass/cli.py
src/indicpass/hub.py            src/indicpass/logging_utils.py
src/indicpass/records.py        src/indicpass/script_utils.py
```

They were left alone deliberately: they are dataset-pipeline plumbing unrelated
to the research result, and rewriting ten files to obtain a green global lint
would put unreviewed churn into the release diff. Every file the password
engine and the milestones touch is clean:

```bash
python -m ruff check src/indicpass/password src/indicpass/figures.py \
    scripts/milestone5_oov_attack.py scripts/final_report.py \
    scripts/verify_reproducibility.py tests/
```

### Report hashes

`scripts/verify_reproducibility.py` runs every pipeline twice in separate
processes and compares the **canonical payload** — the report JSON with
`generated_at` and the self-referential `reproducibility` block removed, and the
remaining keys sorted. All eight are byte-identical:

```
indicdict_coverage_hin    sha256:06366a6d7c8a8b140ec5bba7475be83d6a2506bb361a6254865a0602ea2f601f
password_benchmark_hin    sha256:65fb95a5f27677051377d6882149b6c1ab7b66f623db5dbb0473117719b5de97
mined_tier_ablation       sha256:44f64f0672511ac6e49b1314c041150a81db1f19af99fe340cbf584c87a8acf2
guess_model_sensitivity   sha256:ab5905b88b7637f7b784c4bcc8ce6c8192be9b3d3f25ed4d72c75c1215f54c20
pcfg_benchmark_hin        sha256:22ec6cd0b3b2f37d8e59f445631e6996cb3a1a409ff7102d6ff038cb333bf020
pcfg_targeted_hin         sha256:b14a55af21273336b8b63b96997f718dbbf4a0828c22ff4a83f42e01d51dff17
reference_attack_hin      sha256:d2281449da676cb07de6b521aa1f4cfa7822c3c1e4766a2ece414a3a21f0beae
milestone5_oov_attack     sha256:d1e94bfefe9449390eeb7f062bae6f976a7c86b5890730f3d1b83b41bfd7b2b7
```

The file on disk will **not** match these digests: it carries a timestamp.
Compare the canonical payload, which is what step 8 does.

### Headline numbers

| | |
| --- | --- |
| M4 coverage | 528 / 1,400 (37.7%) |
| M4 out-of-lexicon coverage | 0 / 872 |
| M5 coverage | 1,091 / 1,400 (77.9%) |
| M5 out-of-lexicon Indic coverage | 468 / 468 (100%) |
| M5 universe | 6,158,855,235,274,035 = 10^15.79, levels 0–70 |
| Spearman on out-of-lexicon Indic | M2 0.919, M3 0.858, zxcvbn 0.772 |
| MAE on out-of-lexicon Indic | M2 1.128, M3 1.037, zxcvbn 2.003 |
| out-of-lexicon Hindi vs random separation | 6.49 orders of magnitude |
| M5 verdict | partially supported (calibration yes, ordering no) |

---

## 6. What is *not* committed, and why

* **No password corpus, leaked or otherwise.** None is used anywhere in this
  project.
* **No cracking wordlist.** Neither attack materialises one; both count.
* **No generated benchmark passwords.** The corpus lives in memory for the
  length of a run. Reports key their rows on `sample_id`, and a test asserts
  that no committed report places a password within 400 characters of the id
  that used it.
* **No `sample_id` → password mapping**, in any report, in any format.
* **No model weights or raw datasets** (gitignored; see `.gitignore`).
* **No credentials.** `.env` is gitignored; `.env.example` is committed and
  contains no secret.
* **No machine-local paths.** `.claude/` is gitignored because its command
  allowlist accumulates absolute paths from whichever machine approved them.

---

## 7. If a number does not reproduce

1. Check the dictionary hash in §3. Almost every downstream number depends on
   it, and a rebuilt dictionary from a different model checkpoint will move all
   of them.
2. Check `data/pcfg/pcfg_hin.json` loads without a fingerprint error. If it
   refuses, the grammar and the dictionary disagree; re-run step 4.
3. Run `python scripts/verify_reproducibility.py --languages hin`. It names the
   first key at which two runs differ, rather than only reporting that they do.
4. Check `zxcvbn` is 4.5.0. A different version changes every baseline column.
5. Confirm the corpus digest matches §3. If it does not, `evaluation.seed` or
   the generator version has changed, and no result is comparable across that
   change — which is why both are written into every report.
