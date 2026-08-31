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

**Hindi dataset processed and validated; training pipeline built and sanity-checked.**
No full-scale model has been trained yet.

| Phase | State |
| --- | --- |
| Environment, dependencies, `.gitignore` | done |
| Configuration (`config/*.yaml`) | done |
| Dataset pipeline (download / inspect / preprocess / validate) | done |
| Documentation | done |
| Aksharantar Hindi: downloaded, preprocessed, validated | done — 1,315,562 records |
| Tokenizer, model, trainer, metrics, inference | done |
| Overfit sanity check (500 real records) | **passed — CER 0.0000** |
| Full Hindi baseline training | not started |
| Tamil / Telugu / Kannada / Malayalam | not started |
| Backend / frontend | not started |

Processed Hindi splits:

| Split | Records |
| --- | ---: |
| train | 1,299,143 |
| validation | 6,307 |
| test | 10,112 |

Preprocessing is deterministic — two runs produced byte-identical output with
matching SHA256 hashes — so these files are reproduced, not copied, on a new
machine.

---

## Project structure

```
IndicPass/
├── config/                  # all tunable settings; relative paths only
│   ├── project.yaml         #   paths, seed, logging
│   ├── languages.yaml       #   target languages, scripts, Unicode ranges
│   ├── dataset.yaml         #   sources, preprocessing, splits, thresholds
│   └── training/            #   training hyper-parameters
│       ├── hindi_debug.yaml     #     500 records — the overfit test
│       └── hindi_baseline.yaml  #     the full run
├── data/
│   ├── raw/                 # immutable downloads — never edited in place
│   │   ├── aksharantar/
│   │   └── other/
│   ├── processed/           # standardized JSONL, generated
│   └── synthetic/           # generated code-mixed data (later phase)
├── docs/
│   ├── architecture.md          # how the pieces fit together
│   ├── dataset_pipeline.md      # the four data scripts + corpus ambiguity
│   ├── training.md              # tokenizer, model, trainer, metrics
│   ├── gpu_training_setup.md    # setting up + training on a CUDA laptop
│   └── development_workflow.md  # day-to-day + the two-PC setup
├── models/
│   ├── checkpoints/         # training-time snapshots (training PC)
│   └── final/               # portable inference bundles
├── notebooks/               # exploration
├── requirements/
│   ├── base.txt             # dataset pipeline — the only one installed now
│   ├── dev.txt              # + tests, linting, notebooks
│   └── ml.txt               # + torch/transformers — training PC only
├── results/
│   ├── logs/                # rotated run logs (git-ignored)
│   └── reports/             # validation reports
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
│   └── predict.py           # inference from a checkpoint
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
│   └── seeding.py           # seeds, device selection, RNG state
└── tests/                   # 184 tests
```

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

There are three requirement files; install what you need.

| File | Contents | Install it when |
| --- | --- | --- |
| `requirements/base.txt` | dataset pipeline only | always |
| `requirements/dev.txt` | + pytest, ruff, mypy, notebooks | you are running tests |
| `requirements/ml.txt` | + torch, tensorboard | you are training or running inference |

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
