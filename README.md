# IndicPass

Multilingual Indian transliteration and code-mixed text processing.

IndicPass takes Romanized or code-mixed Indic text and renders it in the
appropriate native script:

```
"namaste kaise ho"      ->  "नमस्ते कैसे हो"
"vanakkam epdi iruka"   ->  "வணக்கம் எப்படி இருக்க"
```

Romanized Indic words may appear mixed with English, and the system is expected
to leave genuine English alone.

**Target languages**

| Code | Language | Romanized as | Script | Unicode block |
| --- | --- | --- | --- | --- |
| `hin` | Hindi | Hinglish | Devanagari | U+0900–U+097F |
| `tam` | Tamil | Tanglish | Tamil | U+0B80–U+0BFF |
| `tel` | Telugu | Tenglish | Telugu | U+0C00–U+0C7F |
| `kan` | Kannada | Kanglish | Kannada | U+0C80–U+0CFF |
| `mal` | Malayalam | Manglish | Malayalam | U+0D00–U+0D7F |

ISO 639-3 codes are canonical throughout the project. The CLIs also accept
639-1 codes and plain names (`hi`, `Hindi`, `hinglish` all resolve to `hin`).

---

## Status

**Research implementation frozen at `v1.0-research`.** Hindi baseline trained
and scored on held-out test data; password-strength engine complete through
Milestone 5. All three estimators are scored against **two independent bounded
attackers** whose ranks are observed rather than estimated — one a wordlist, one
a character model that can reach spellings the dictionary has never seen.

**IndicPass (M2) predicts the attack *ordering* best; the PCFG (M3) predicts its
*magnitude* best.** The split holds on both attackers, on in-lexicon and
out-of-lexicon populations alike, and in every ablation arm including those that
share no evidence with any estimator. zxcvbn's error is roughly twice either
Indic estimator's. M3's out-of-lexicon mechanism is confirmed — an unseen Hindi
spelling is reached 6.49 orders of magnitude earlier than a random string — but
it does not make M3 the better ranker, and that negative result is kept.

Full synthesis: `results/reports/final_report.md`. Reproduction:
`docs/REPRODUCING.md`.

| Phase | State |
| --- | --- |
| Environment, dependencies, `.gitignore` | done |
| Configuration (`config/*.yaml`) | done |
| Dataset pipeline (download / inspect / preprocess / validate) | done |
| Documentation | done |
| Aksharantar Hindi: downloaded, preprocessed, validated | done — 1,315,562 records |
| Tokenizer, model, trainer, metrics, inference | done |
| Overfit sanity check (500 real records) | **passed — CER 0.0000** |
| Full Hindi baseline training | done — `models/final/indicpass-hin-v1/` |
| Held-out test evaluation | **done — CER 0.1084, exact match 56.18%** |
| Password engine: IndicDict, matcher, guess model, 0–4 score, CLI | done (Milestone 1) |
| Frequency-ranked dictionary, match classes, zxcvbn baseline, benchmark | done (Milestone 2) |
| Indic PCFG: learned terminals, Monte-Carlo guess numbers | done (Milestone 3) — *does not beat the Milestone 2 estimator; see below* |
| Reference-attack validation: bounded enumeration, observed ranks | done (Milestone 4) — *synthetic attack, not a real cracking run* |
| Out-of-lexicon attack validation: character-model enumeration | done (Milestone 5) — *reaches 468/468 out-of-lexicon Indic targets* |
| Final audit, reproducibility verification, final report | done — *8/8 reports byte-identical across separate processes* |
| Password engine: leet/separator mangling | not started |
| Validation against a **real** cracking run on leaked data | not started — still the blocker on any real-world accuracy claim |
| Tamil / Telugu / Kannada / Malayalam | not started |
| Backend / frontend | done — thin FastAPI adapter + Next.js UI over the existing engine; see `docs/frontend.md` |

Processed Hindi splits:

| Split | Records |
| --- | ---: |
| train | 1,299,143 |
| validation | 6,307 |
| test | 10,112 |

### Transliteration accuracy

| Metric | Split | Value | Role |
| --- | --- | ---: | --- |
| CER | validation | 0.1048 | **model selection** — the checkpoint was chosen by this |
| CER | test | **0.1084** | **held-out result** |
| Exact match | test | **56.18%** | held-out result |

The validation figure is not a held-out result and must not be quoted as one.
`scripts/evaluate.py` writes both into every report so the distinction survives.
Full report: `results/reports/test_eval_hin_v1.md`.

Preprocessing is deterministic — two runs produced byte-identical output with
matching SHA256 hashes — so these files are reproduced, not copied, on a new
machine.

---

## Project structure

```
IndicPass/
├── api/                     # thin FastAPI adapter over the engine below
│   ├── main.py              #   POST /api/analyze, GET /api/health
│   └── tests/               #   API-level tests; run separately (see docs/frontend.md)
├── frontend/                # Next.js + TypeScript + Tailwind UI, calls api/
├── config/                  # all tunable settings; relative paths only
│   ├── project.yaml         #   paths, seed, logging
│   ├── languages.yaml       #   target languages, scripts, Unicode ranges
│   ├── dataset.yaml         #   sources, preprocessing, splits, thresholds
│   ├── password.yaml        #   guess model, frequency source, tiers,
│   │                        #     match classes, 0–4 thresholds, baseline
│   └── training/            #   training hyper-parameters
│       ├── hindi_debug.yaml     #     500 records — the overfit test
│       └── hindi_baseline.yaml  #     the full run
├── data/
│   ├── raw/                 # immutable downloads — never edited in place
│   │   ├── aksharantar/
│   │   └── other/
│   ├── processed/           # standardized JSONL, generated
│   ├── dictionaries/        # IndicDict, generated; .meta.json is committed
│   └── synthetic/           # generated code-mixed data (later phase)
├── docs/
│   ├── architecture.md          # how the pieces fit together
│   ├── dataset_pipeline.md      # the four data scripts + corpus ambiguity
│   ├── training.md              # tokenizer, model, trainer, metrics
│   ├── password_strength_design.md  # the guess model, written out in full
│   ├── REPRODUCING.md           # environment, seeds, hashes, exact commands
│   ├── gpu_training_setup.md    # setting up + training on a CUDA laptop
│   └── development_workflow.md  # day-to-day + the two-PC setup
├── models/
│   ├── checkpoints/         # training-time snapshots (training PC)
│   └── final/               # portable inference bundles
├── notebooks/               # exploration
├── requirements/
│   ├── base.txt             # dataset pipeline + password engine (zxcvbn, wordfreq)
│   ├── dev.txt              # + tests, linting, notebooks
│   ├── ml.txt               # + torch/transformers — training PC only
│   └── api.txt              # + FastAPI/uvicorn — running api/ only
├── results/
│   ├── figures/             # SVG figures for the final report
│   ├── logs/                # rotated run logs (git-ignored)
│   └── reports/             # dataset validation, held-out evaluation,
│                            #   dictionary coverage, benchmark, ablations,
│                            #   the two attacks, and final_report.{md,json}
├── runs/                    # training output, git-ignored
│   └── <run name>/
│       ├── checkpoints/     #   best.pt (lowest val CER) + last.pt
│       ├── tokenizer/       #   the vocabularies this run was fitted with
│       ├── config.yaml      #   the resolved config that actually ran
│       └── metrics.json     #   per-epoch history
├── scripts/                 # runnable CLIs, all from the project root
│   ├── download_datasets.py
│   ├── inspect_dataset.py
│   ├── preprocess_dataset.py
│   ├── validate_dataset.py
│   ├── train.py             # training + resume
│   ├── predict.py           # inference from a checkpoint
│   ├── evaluate.py          # held-out test scoring -> results/reports/
│   ├── export_bundle.py     # checkpoint -> portable safetensors bundle
│   ├── build_indicdict.py   # offline: model -> frequency-ranked dictionary
│   ├── check_password.py    # analyse one password
│   ├── indicdict_coverage.py    # what the dictionary does and does not hold
│   ├── password_benchmark.py    # IndicPass vs zxcvbn + every ablation
│   ├── milestone5_oov_attack.py # the OOV attack + bootstrap + verdict
│   ├── verify_reproducibility.py # every pipeline twice, byte-compared
│   ├── final_report.py      # assembles final_report.{md,json} + figures
│   ├── train_pcfg.py        # offline: dictionary -> grammar + guess curve
│   ├── pcfg_benchmark.py    # PCFG vs zxcvbn, targeted cases, random control
│   └── reference_attack.py  # all three estimators vs an observed cracking order
├── src/indicpass/           # the importable package
│   ├── config.py            # YAML loading, path resolution, languages
│   ├── records.py           # the standard record schema + JSONL I/O
│   ├── script_utils.py      # Unicode / script validity helpers
│   ├── hub.py               # Hugging Face listing, sizing, download
│   ├── logging_utils.py     # console + rotating file logging
│   ├── cli.py               # shared argparse plumbing
│   ├── tokenizer.py         # character vocabularies (train-split only)
│   ├── data.py              # Dataset, collate, DataLoader
│   ├── model.py             # BiLSTM encoder + attention + LSTM decoder
│   ├── metrics.py           # CER (primary) and exact match
│   ├── trainer.py           # training loop, checkpoints, evaluation
│   ├── inference.py         # load a bundle/checkpoint, decode words
│   ├── figures.py           # SVG charts for the final report, stdlib only
│   ├── seeding.py           # seeds, device selection, RNG state
│   └── password/            # the password-strength engine
│       ├── dictionary.py    #   IndicDict: ranks, provenance tiers
│       ├── frequency.py     #   the external frequency table + its provenance
│       ├── matcher.py       #   find spans, and grade how good each hit is
│       ├── mangling.py      #   case transformations and their cost
│       ├── patterns.py      #   digits, years, symbols, repeats
│       ├── scoring.py       #   optimal segmentation, 0–4 scale
│       ├── meter.py         #   the object that ties those together
│       ├── baseline.py      #   PasswordStrengthBaseline -> ZxcvbnBaseline
│       ├── benchmark.py     #   the generated, controlled password set
│       ├── experiment.py    #   comparison statistics and ablation helpers
│       ├── result.py        #   result type; redacts the password
│       ├── reference_attack.py  # Milestone 4: the bounded wordlist attack
│       ├── character_attack.py  # Milestone 5: the OOV-capable attack
│       ├── oov.py           #   Milestone 5: the in-/out-of-lexicon partition
│       ├── uncertainty.py   #   Milestone 5: bootstrap confidence intervals
│       ├── validation.py    #   Milestone 4: correlations, errors, calibration
│       └── pcfg/            #   Milestone 3: the probability model
│           ├── ngram.py     #     character model over Romanized spellings
│           ├── grammar.py   #     priors, terminals, sampling
│           ├── parser.py    #     the maximum-probability derivation
│           ├── estimator.py #     probability -> guess number (Monte Carlo)
│           ├── artifact.py  #     the committed curve + its fingerprint
│           └── probe.py     #     targeted cases and the random control
└── tests/                   # 785 tests
```

The password engine never runs the neural model. The transliterator's whole
contribution is made offline by `build_indicdict.py`; scoring is a dictionary
lookup. See `docs/password_strength_design.md`.

---

## Setup on a new machine

Requires **Python 3.10 or newer** and Git. Nothing else is assumed: no
pre-existing virtual environment, no datasets, no hidden local files. Every
step below has been run end to end on a clean tree.

Run every command from the project root.

### 1. Clone

```bash
git clone <REPOSITORY_URL>
cd IndicPass
```

### 2. Create a virtual environment

The repository does **not** ship one — `.venv/` is git-ignored, so you build
your own.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script, allow it for this session:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

There are four requirement files; install what you need.

| File | Contents | Install it when |
| --- | --- | --- |
| `requirements/base.txt` | dataset pipeline only | always |
| `requirements/dev.txt` | + pytest, ruff, mypy, notebooks | you are running tests |
| `requirements/ml.txt` | + torch, tensorboard | you are training or running inference |
| `requirements/api.txt` | + FastAPI, uvicorn | you are running `api/` (see `docs/frontend.md`) |

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements/dev.txt   # base + tests
python -m pip install -r requirements/ml.txt    # + training
```

Installing the package itself is optional — the scripts add `src/` to
`sys.path` on their own. For `import indicpass` to work from anywhere:

```bash
python -m pip install -e .
```

Optional, and only for gated or private Hugging Face repositories (Aksharantar
is public, so you can skip this):

```bash
cp .env.example .env        # Linux / macOS
Copy-Item .env.example .env # Windows
# then set HF_TOKEN inside .env
```

### 4. Verify the install

```bash
python -m pytest
```

Expect **184 passed**. With `ml.txt` not installed, expect **137 passed** — the
47 training tests skip themselves rather than failing, so the dataset pipeline
is testable on a machine that never trains.

### 5. Verify the GPU

```bash
nvidia-smi
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

| `cuda.is_available()` | Meaning |
| --- | --- |
| `True` | A CUDA GPU was found and will be used. |
| `False` | CPU only. Fine for the debug run; far too slow for full training. |

`False` on a machine that *does* have an NVIDIA GPU means the installed torch
build does not match your driver. Install torch from PyTorch's own index
first, picking the CUDA version `nvidia-smi` reports:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r requirements/ml.txt
```

### 6. Acquire the raw Hindi dataset

Downloads one 33 MB archive — not the full 695 MB corpus. It prints a plan and
asks before transferring anything.

```bash
python scripts/download_datasets.py --plan-only            # see the plan first
python scripts/download_datasets.py --languages hin        # then fetch
```

### 7. Preprocess

Raw archives → standardized, deduplicated, split JSONL. Takes about 7 minutes.
Raw data is never modified.

```bash
python scripts/preprocess_dataset.py --languages hin --dry-run   # optional
python scripts/preprocess_dataset.py --languages hin
```

### 8. Validate

The quality gate. Writes a report and exits non-zero on a threshold breach.

```bash
python scripts/validate_dataset.py --languages hin
```

You should get 1,299,143 / 6,307 / 10,112 records — identical to the numbers in
the Status table above, because preprocessing is deterministic. If they differ,
stop and investigate before training.

### 9. Debug training run — do this before anything else

500 examples, ~5 minutes on CPU. This is a correctness test, not an
experiment: a working model **must** drive CER to near zero here.

```bash
python scripts/train.py --config config/training/hindi_debug.yaml
```

Expect the training loss to collapse and `val CER` to reach `0.0000`. If it
does not, something is broken — do not start full training. See
[docs/training.md](docs/training.md).

### 10. Full training

Work up through the stages rather than jumping to the end:

```bash
# Stage 2 -- 10k records, pipeline shakeout (~10 min on GPU)
python scripts/train.py --config config/training/hindi_baseline.yaml \
    --max-train-records 10000 --name hindi_10k --epochs 5

# Stage 3 -- 100k records, is the architecture learning? (~1-2 h on GPU)
python scripts/train.py --config config/training/hindi_baseline.yaml \
    --max-train-records 100000 --name hindi_100k --epochs 8

# Stage 4 -- the full 1,299,143-record baseline
python scripts/train.py --config config/training/hindi_baseline.yaml
```

### 11. Resume an interrupted run

Restores model, optimizer, scheduler and RNG state from `last.pt`:

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml --resume
```

### 12. Inference

```bash
python scripts/predict.py \
    --checkpoint runs/hindi_baseline_v1/checkpoints/best.pt \
    --text "namaste"
```

### 13. Score the held-out test split

```bash
python scripts/evaluate.py --languages hin
```

Writes `results/reports/test_eval_hin_v1.{json,md}`. The report labels the test
number as held out and keeps the validation number beside it, marked as model
selection, so the two cannot be confused later.

---

## Password strength engine

Estimates how many guesses a password costs an attacker who knows that
Romanized Indic words are password material. The design — every formula, and
what is deliberately *not* claimed — is in `docs/password_strength_design.md`.

```bash
# Once: build the dictionary offline from the trained transliterator (~35 min CPU)
python scripts/build_indicdict.py --languages hin

# Then: scoring is a dictionary lookup, no model involved
python scripts/check_password.py --password "bharat2024"
python scripts/check_password.py --password "bharat2024" --json

# The measurements behind every claim below
python scripts/indicdict_coverage.py --languages hin
python scripts/password_benchmark.py --languages hin

# Milestone 3: the PCFG. Needs no torch and no network -- the grammar is
# refitted from the committed dictionary in ~20s.
python scripts/train_pcfg.py --languages hin
python scripts/pcfg_benchmark.py --languages hin

# Milestone 4: score all three estimators against an observed cracking order.
# Builds no wordlist -- the enumeration is counted, not materialised.
python scripts/reference_attack.py --languages hin

# Milestone 5: the same, against an attacker whose candidates come from a
# character model instead of a wordlist, so that a spelling missing from
# IndicDict is reachable too. This is the one that tests M3's OOV claim.
python scripts/milestone5_oov_attack.py --languages hin

# Every pipeline twice, in separate processes, compared byte for byte
python scripts/verify_reproducibility.py --languages hin

# The final report and its figures, assembled from the reports above
python scripts/final_report.py
```

Run it without `--password` to be prompted without echo — a password given on
the command line ends up in your shell history.

The primary quantity is `guess_number`, an estimated number of attempts. It is
**not** entropy, and nothing in the code calls it that: no probability
distribution over passwords is estimated anywhere. `log10_guesses` is its
base-10 logarithm; the 0–4 score counts how many of the configured thresholds
in `config/password.yaml` it reaches.

**The 0–4 score comes from M2 alone.** M3 and zxcvbn ride alongside it in the
result object and never replace it. That is a measured decision, not an
accident of ordering: a 0–4 band is an *ordering* device, M2 has the higher rank
correlation with both reference attackers, and M3's advantage is in magnitude,
which the band throws away. `PasswordStrengthResult.pcfg` and `.baseline` carry
the other two verbatim so that a caller who needs a calibrated *number* rather
than a band can read M3's directly. No fusion of the two is shipped, because
fitting one would require a corpus disjoint from the evaluation benchmark and
this project has none — see §16.8 of the design doc.

A word's cost is its position in an attacker's wordlist, from one of two
policies that every result reports by name: `observed_rank` (the native form's
Zipf frequency in `wordfreq-3.1.1/hi/small`, covering 40,966 of 297,747 entries)
or `tier_fallback` (a documented provenance rule for the rest). Nothing is
substituted for an unknown frequency.

### How to read these results

Six statements that the reports depend on and that are easy to overstate:

1. **The attacks are bounded reference models, not claims about real
   attackers.** M4 and M5 are each one fully specified attacker. Neither has a
   leaked-password list, leet substitution, keyboard walks or targeted personal
   data, and no leaked corpus is used anywhere in this project. An estimator
   that predicts these attacks well may predict another badly.
2. **"Rank" means the position at which a specific attacker emits a specific
   password.** It is computed exactly, by inverting that attacker's ordering —
   not sampled, not extrapolated. It is a fact about the attack, not an estimate
   of what a real attacker would need.
3. **An unreachable candidate receives no rank.** Never the universe size, never
   a censored bound, never a substituted value. It counts towards coverage and
   towards nothing else, and every metric is reported with its coverage beside
   it so the conditioning is visible. `unreachable != universe_size`.
4. **M2 and M3 measure different aspects of attackability.** M2 asks what the
   cheapest explanation costs an attacker with a wordlist; M3 asks how probable
   the string is under a grammar, and counts. M2 wins ordering, M3 wins
   magnitude, and collapsing them into one score would hide that.
5. **M3's out-of-lexicon mechanism is supported; M3 is not the better ranker.**
   The character model really does price unseen Hindi spellings like Hindi.
   That was M3's hypothesis and it holds. It did not translate into better rank
   correlation than M2, and the report says so.
6. **zxcvbn is not an Indic-specific attacker** and is not being criticised for
   failing at something it was not built for. It is the measurement of what a
   deployed generic meter does with this population, and it is the reason a
   comparative claim is possible at all.

And one about the data: **the password benchmark is synthetic.** 1,400 samples
generated from a committed, hand-written Romanized Hindi word bank. The
transliteration corpus and the held-out CER are real; the passwords are not
observed passwords, and no claim about the distribution of real Indian passwords
is supported by them.

### What the benchmark found

1,400 generated passwords across seven categories, IndicPass and zxcvbn scoring
each one in the same call. Reports in `results/reports/`.

| | |
| --- | --- |
| The Indic lexicon lowers Indic estimates by | −0.79 to −0.93 log10 |
| …and random controls by | **−0.00 log10** |
| Information it adds beyond zxcvbn, on Indic categories | −0.25 to −0.48 log10, on 20–32% of samples |
| …on English and random controls | 0.00 on 398 of 400 samples |
| Mined-tier contribution | ≤0.04 log10 — it is *not* carrying the result |

Stated plainly: **IndicPass alone does not beat zxcvbn.** It reads +3.19 log10
above it on English passwords, because it has no common-password wordlist at
all. The deployable object is `min(IndicPass, zxcvbn)` — guessing cost is a
minimum over the attacker's options.

Two limits that shape everything above. Aksharantar covers 8 of the 15 common
Romanized Hindi probe words; `namaste`, `sharma`, `maa`, `ghar` and `dost` are
absent from the corpus *at source*, and were not added by hand to hide it. And
7 of 10 generic English password words *are* in the "Hindi" dictionary, so the
English control is weaker than its name suggests. Both are measured in
`results/reports/indicdict_coverage_hin.md`.

No claim here is validated against a real cracking run. "Fewer guesses" is a
statement about two models, not about reality.

### What the PCFG found (Milestone 3)

A probabilistic grammar over password structure, with **learned terminals** —
`P(word)` from the same wordfreq join, and a character n-gram over all 297,747
Romanized spellings — and an explicit maximum-entropy prior for the structure,
because learning that needs a password corpus and this repository has none.
Guess numbers come from Monte-Carlo counting (Dell'Amico & Filippone 2015), not
from a formula: no `k!`, no `D^(k-1)`.

Three findings, in the order that matters.

**The random control is clean.** 0.0% of random strings in any cell were priced
below enumerating them, and removing the lexicon changes random controls by
+0.00 log10 while costing +0.36 on `indic_word` and +0.52 on `indic_year`. The
grammar does not invent structure.

**The character model generalised, and it does not matter.** Hindi words the
dictionary is *missing* cost 0.936 log10 per character against 0.935 for words
it trained on — it learned the shape of the language, not a list — and random
strings cost 2.204. But the brute-force floor charges 1.000, so only 0.064 of
that 1.27 log10 discrimination can ever reach an estimate. Measured, not
assumed.

**The PCFG does not beat the Milestone 2 estimator.** Information added beyond
zxcvbn on `indic_word`: −0.13 log10 for the PCFG against −0.37 for Milestone 2.
Adding it to `min(Milestone 2, zxcvbn)` improves 2 more samples out of 1,400.
It reads *higher* than zxcvbn in every category, because its guess number counts
passwords of every structure that outrank the target rather than only those
sharing the assumed one — the more complete attacker model, and the larger
number. **This contradicts the hypothesis and is reported rather than tuned
around.** The primary estimator is unchanged.

The one genuinely reassuring result: the parts of the model that *cannot* be
learned from anything here — the segment prior, the category prior — move every
category by ≤0.03 and ≤0.25 log10 respectively, and re-seeding the Monte-Carlo
estimator moves nothing at all. `results/reports/pcfg_benchmark_hin.md`.

### What the reference attack found (Milestone 4)

Milestones 2 and 3 compared estimators with each other, which cannot say which
one is *right*. Milestone 4 adds the first quantity in the project that is not
a model output: the position at which a fully specified attacker actually emits
a password.

The attacker is a wordlist crossed with an ordered rule set — the hashcat/John
model — over all 297,747 IndicDict spellings, 63 rules, and a universe of
**10^15.85 candidates**. Nothing is enumerated: every rule is a product with a
known factorisation, so a rank is recovered by inverting it. **No cracking
wordlist exists at any point.** The module imports no estimator, and two tests
enforce that — one parses its imports, one ranks a corpus with all three
estimators replaced by objects that raise on contact.

**The two questions have different answers, and both are stable.**

| | Spearman | mean error | MAE | within ±1.0 |
| --- | ---: | ---: | ---: | ---: |
| **IndicPass (M2)** | **0.900** | −1.951 | 1.955 | 26% |
| **PCFG (M3)** | 0.806 | **−0.377** | **1.370** | **50%** |
| zxcvbn 4.5.0 | 0.592 | −2.417 | 2.828 | 14% |

IndicPass predicts the *ordering* best; the PCFG predicts the *magnitude* best.
That holds in **all six attacker arms**, including the two whose wordlist order
shares no evidence with any estimator — which is what makes it a statement
about the estimators rather than about the frequency table they were built on.

**zxcvbn's rank correlation on bare Romanized Hindi words is 0.005.** It carries
essentially no information about the order an Indic wordlist attack reaches
them in. That is the project's founding hypothesis, measured for the first time
against something other than another model.

Three things this does **not** show, stated because they are easy to overstate.
Coverage is 37.7%, and the attack **cannot rank an unseen spelling at all** —
0 of 872 — so the population the PCFG's character model exists for is outside
the measurement entirely. The `min()` combinations score worse than their parts,
which is correct: `min` is the right quantity for security and the wrong one for
predicting one specific attacker. And this is a synthetic attack, so nothing
here licenses a real-world cracking claim. `results/reports/reference_attack_hin.md`
and `docs/password_strength_design.md` §15.

### What the out-of-lexicon attack found (Milestone 5)

The 872 unrankable targets above are exactly the population Milestone 3 was
built for, so Milestone 5 replaces the wordlist with a character model. A
candidate becomes `case(stem) + suffix` where **stem is any string over the 26
lower-case letters** within a length band — so an out-of-lexicon spelling is
reachable on the same terms as one the dictionary holds. Candidates are ordered
by an integer quantised cost; the number at each cost is a dynamic programme, so
a universe of 10^22 stems is **counted without being built** and a rank is
recovered by inversion. Same 10^16 budget as Milestone 4, so the coverage
difference is about the candidate model and not about how long each attacker ran.

| | M4 (wordlist) | M5 (character model) |
| --- | ---: | ---: |
| all 1,400 targets | 528 (37.7%) | **1,091 (77.9%)** |
| out-of-lexicon Indic | **0 of 872** | **468 of 468 (100%)** |

On those 468 out-of-lexicon Indic targets, with paired bootstrap intervals:

| | Spearman | MAE | RMSE | calibration slope |
| --- | ---: | ---: | ---: | ---: |
| **IndicPass (M2)** | **0.919** | 1.128 | 1.397 | **1.005** |
| **PCFG (M3)** | 0.858 | **1.037** | **1.274** | 0.882 |
| zxcvbn 4.5.0 | 0.772 | 2.003 | 2.464 | 0.914 |

**The same split, on a disjoint population, under an attacker with no wordlist**
— and it holds in all seven arms, including the `uniform` arm that has no
character statistics at all and gives no estimator an informational advantage.

The strongest positive result is the control. This attack *can* reach a random
lower-case string, so the question is how much later: median log10 rank is 8.14
for out-of-lexicon Hindi and 14.62 for random controls — **6.49 orders of
magnitude of separation**. A character model trained only on a transliteration
dictionary really does place Hindi spellings it has never seen far earlier in an
attack than noise, which confirms M3's proposed mechanism independently of M3.

**It does not make M3 the better estimator.** By a rule fixed before the numbers
were computed, M3's out-of-lexicon claim is **partially supported**: calibration
yes (MAE −0.091, CI [−0.141, −0.042]), ordering no (Spearman −0.060, CI
[−0.078, −0.044]). The negative half is kept. `results/reports/milestone5_oov_attack.md`
and `docs/password_strength_design.md` §16.

### The final report

`results/reports/final_report.md` is the synthesis: abstract, threat model,
every milestone's result, the M2/M3 trade-off, the zxcvbn comparison, the
controls, the bootstrap methodology, limitations, threats to validity and the
reproduction commands. Figures are in `results/figures/` as SVG. Every number in
it is read from a committed milestone report and carries a pointer to the file
and key it came from — nothing is recomputed there.

`docs/REPRODUCING.md` has the environment, the seeds, the artefact hashes, the
expected test count and the expected report digests.

---

## Frontend & API

A thin FastAPI adapter (`api/`) and a Next.js interface (`frontend/`) over
the password-strength engine above. No analysis logic lives in either — every
number the page shows comes from the same `IndicPassMeter` object
`scripts/check_password.py` has always used.

```bash
python -m pip install -r requirements/api.txt
python -m uvicorn api.main:app --reload --port 8000    # terminal 1

cd frontend && npm install && npm run dev               # terminal 2, http://localhost:3000
```

Full architecture, the API contract, security notes and test instructions:
[docs/frontend.md](docs/frontend.md).

---

## GPU sizing

Start conservative. A batch size that does not fit fails partway through an
epoch, not at startup, so an optimistic guess costs you the whole epoch.

| Hardware | `batch_size` | `hidden_dim` | Notes |
| --- | ---: | ---: | --- |
| RTX 3050 4 GB | 64 | 512 | The default 128 is tight at 4 GB; drop to 32 if you hit OOM. |
| RTX 3050 6 GB | 128 | 512 | The shipped default. |
| Colab T4 16 GB | 256 | 512 | Raise `eval_batch_size` to 512 too. |
| CPU only | 32 | 256 | Debug config only. Full training is impractical — days, not hours. |

Override without editing the config:

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml --batch-size 64
```

If you hit CUDA out-of-memory, halve `batch_size` first; reduce `hidden_dim`
only if that is not enough.

---

## Dataset workflow

Four commands, run in order from the project root. Each is safe to run on its
own and explains what to do next.

```bash
# 1. Look before you leap: repo metadata and per-language sizes. No download.
python scripts/inspect_dataset.py --remote

# 2. See exactly which files would be fetched, and how many bytes.
python scripts/download_datasets.py --plan-only

# 3. Download only the languages you asked for, after confirming the plan.
python scripts/download_datasets.py --languages hin tam

# 4. Look at what actually landed on disk.
python scripts/inspect_dataset.py --local --samples 5

# 5. Raw -> standardized, deduplicated JSONL. Raw data is never modified.
python scripts/preprocess_dataset.py --dry-run
python scripts/preprocess_dataset.py

# 6. Quality gate. Writes a report; exits non-zero on a threshold breach.
python scripts/validate_dataset.py
```

Full detail: [docs/dataset_pipeline.md](docs/dataset_pipeline.md).
Training: [docs/training.md](docs/training.md).
Setting this up on a CUDA laptop: [docs/gpu_training_setup.md](docs/gpu_training_setup.md).

### Reproducing the dataset rather than copying it

The processed Hindi corpus is 270 MB and is **not** in Git. It does not need
to be: preprocessing is deterministic, so running the three commands above on
another machine reproduces it byte for byte.

What Git *does* carry is the provenance needed to make that exact:

- `data/raw/aksharantar/download_manifest.json` pins the upstream revision
  (`e418c1fc…`), the exact files fetched and their byte counts.
- `data/processed/preprocess_manifest.json` records every preprocessing
  setting that produced the current output, plus per-language counts.

If your numbers differ from the Status table, one of those two changed —
compare the manifests before looking anywhere else.

### The processed record

Every source is flattened into one shape, so nothing downstream needs to know
where a record came from:

```json
{
  "record_id": "f5a22b75af6e6d74",
  "language": "hin",
  "script": "Deva",
  "source_text": "namaste",
  "target_text": "नमस्ते",
  "dataset_source": "aksharantar",
  "subsource": "Dakshina",
  "split": "train"
}
```

`record_id` is a content hash of `(language, source_text, target_text)`. It is
identical on every machine, which is what makes deduplication and split
assignment reproducible.

`subsource` records the sub-corpus within a dataset — Aksharantar mixes
human-curated `Dakshina` pairs with mined `Wikidata` and `AK-Freq` ones, which
differ in quality. It is optional (empty for sources that do not distinguish
one) and deliberately excluded from `record_id`: the same pair mined from two
sub-corpora is one pair and must deduplicate to one record.

---

## Two-PC setup

The project is designed to run across two machines sharing one Git repository:

- **Development PC** — frontend, backend, dataset inspection, preprocessing,
  inference and testing. CPU only.
- **Training PC** — dataset download and preprocessing, GPU training,
  checkpoints, evaluation.

Datasets and model weights never travel through Git. Only code, configuration
and small provenance manifests do; the manifests let the training PC reproduce
the development PC's exact raw corpus with one command.

A trained model comes back as a self-contained bundle in `models/final/`
(weights, tokenizer, config, inference metadata) transferred out of band.
See [docs/development_workflow.md](docs/development_workflow.md).

---

## First dataset: Aksharantar

[`ai4bharat/Aksharantar`](https://huggingface.co/datasets/ai4bharat/Aksharantar)
— roughly 26M transliteration pairs across 21 Indic languages, the largest
public corpus of its kind.

Two things to keep in mind:

1. **It is word-level, not sentence-level.** Aksharantar gives IndicPass its
   Roman→native lexicon. Turning `"namaste kaise ho"` into a sentence needs
   segmentation and context handling on top, and code-mix detection (which
   words are English?) needs different data again.
2. **Only a fraction of it is needed.** The five target languages are a subset
   of the 21, so `download_datasets.py` resolves and fetches per-language files
   rather than cloning the repository.

---

## Conventions

- All configuration lives in `config/*.yaml`; no paths are hardcoded in code.
- Every configured path is relative to the project root and resolved at runtime.
- `data/raw/` is immutable. Scripts read it and write elsewhere.
- Scripts run from the project root: `python scripts/<name>.py`.
- Anything that downloads or overwrites prints a plan and asks first; `--yes`
  skips the prompt for automation.

## Licence

MIT. Upstream datasets keep their own licences — Aksharantar is CC-BY-4.0.
