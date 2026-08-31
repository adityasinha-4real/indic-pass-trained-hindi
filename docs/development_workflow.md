# Development workflow

Day-to-day work, and how the development PC and the training PC share one
repository without ever pushing a dataset or a model file through Git.

---

## 1. Environment

Python 3.10+. The repository ships with a `.venv` in the project root.

```powershell
# Windows
.\.venv\Scripts\Activate.ps1
```
```bash
# macOS / Linux
source .venv/bin/activate
```

### Which requirements file

| File | Install on | Contains |
| --- | --- | --- |
| `base.txt` | both PCs | PyYAML, python-dotenv, huggingface-hub, pyarrow, tqdm, rich |
| `dev.txt` | both PCs | base + pytest, ruff, black, mypy, jupyterlab |
| `ml.txt` | training PC (and anywhere you run inference) | base + torch, numpy, tensorboard |

```bash
python -m pip install -r requirements/dev.txt
```

Every entry in `base.txt` is imported by code in `src/` or `scripts/`. If you
add one, import it; if you stop importing one, delete it.

`ml.txt` is kept off the development PC by default. A CUDA torch install is
several gigabytes and buys nothing on a machine that only runs the data
pipeline and the backend. Install it on the dev PC when you want to run the
debug training config or CPU inference — the CPU wheel is far smaller:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

The training stack is deliberately minimal: torch, numpy, tensorboard, and
nothing else. The baseline is a character-level seq2seq written directly in
PyTorch — no transformers, no accelerate, no lightning. Adding a framework
would hide roughly 250 lines of model code without removing any of it.

`requirements/base.txt` is the single source of truth for runtime dependencies
— `pyproject.toml` reads it via `[tool.setuptools.dynamic]`, so the two cannot
drift. Add a runtime dependency there, not in both places.

> **Python version.** The current `.venv` is Python 3.14, and torch publishes
> cp314 wheels (2.13.0 verified installed and training on 2026-08-31), so this
> is no longer a constraint. Any version from 3.10 up works; check
> <https://pypi.org/project/torch/#files> if you pick something newer still.

### Optional package install

The scripts put `src/` on `sys.path` themselves, so no install is needed. For
`import indicpass` to work from a notebook or anywhere else:

```bash
python -m pip install -e .
```

### Secrets

```bash
cp .env.example .env     # Copy-Item on Windows
```

Only needed for gated or private Hugging Face repositories. `.env` is
git-ignored; `.env.example` is committed and must never contain a real value.

---

## 2. Daily loop

```bash
python -m pytest              # tests
python -m ruff check .        # lint
python -m ruff format .       # format  (or: python -m black .)
python -m mypy                # types
```

Conventions worth keeping:

- Configuration goes in `config/*.yaml`, never inline in a script.
- Paths come from `config.path("data_processed")`, never a string literal.
- Use `pathlib`, not `os.path` or string concatenation.
- Type hints on anything that crosses a module boundary.
- Errors say what to do next, not just what went wrong.

---

## 3. Two-PC architecture

```
        ┌─────────────────────────────┐         ┌─────────────────────────────┐
        │      DEVELOPMENT PC         │         │        TRAINING PC          │
        │  (CPU, day-to-day work)     │         │  (GPU, long jobs)           │
        ├─────────────────────────────┤         ├─────────────────────────────┤
        │  frontend                   │         │  dataset download           │
        │  backend / API              │         │  preprocessing              │
        │  dataset inspection         │         │  GPU training               │
        │  preprocessing              │         │  checkpointing              │
        │  inference + testing        │         │  evaluation                 │
        │                             │         │                             │
        │  requirements: base, dev    │         │  requirements: base, ml     │
        └──────────────┬──────────────┘         └──────────────┬──────────────┘
                       │                                       │
                       │            ┌───────────┐              │
                       └───────────►│    Git    │◄─────────────┘
                                    │  code +   │
                                    │  config + │
                                    │ manifests │
                                    └───────────┘

                       ┌───────────────────────────────────────┐
                       │  NOT in Git — moved out of band       │
                       │  datasets, checkpoints, model weights │
                       └───────────────────────────────────────┘
```

### What crosses which boundary

| Artefact | Git? | How it moves |
| --- | --- | --- |
| Code, `config/`, docs, tests | yes | `git push` / `git pull` |
| `download_manifest.json`, `preprocess_manifest.json` | yes | Git — small, and enough to rebuild the data |
| Validation reports | yes | Git — small |
| Raw datasets | **no** | Each PC downloads its own, pinned by manifest |
| Processed JSONL | **no** | Regenerated from raw — deterministic, so both PCs get identical output |
| Checkpoints | **no** | Stay on the training PC |
| Final model bundle | **no** | Copied to the development PC out of band |

The reason processed data does not need to travel: preprocessing is
reproducible. Same raw files + same `dataset.yaml` = byte-identical JSONL,
including the train/test partition. The training PC re-runs the pipeline
instead of receiving gigabytes.

`.gitignore` enforces all of this. If a large file ever needs committing, that
is a signal something is wrong with the split of responsibilities.

---

## 4. Setting up the training PC

```bash
git clone <repo-url> IndicPass
cd IndicPass

python -m venv .venv
source .venv/bin/activate            # or .\.venv\Scripts\Activate.ps1

# Install torch matching the GPU driver FIRST, from PyTorch's own index.
python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r requirements/ml.txt

# Rebuild the same data the development PC has.
python scripts/download_datasets.py --languages hin tam tel kan mal
python scripts/preprocess_dataset.py
python scripts/validate_dataset.py
```

To guarantee identical raw data rather than merely equivalent, read the
revision out of the committed manifest and pin it:

```bash
python scripts/download_datasets.py --revision <sha-from-download_manifest.json>
```

Validation must pass on the training PC before a training run starts. That is
what the non-zero exit code is for.

---

## 5. Bringing a trained model back

A model is only useful on the development PC if it arrives complete. Ship it as
one self-contained directory under `models/final/`:

```
models/final/indicpass-hin-v1/
├── model.safetensors          # weights (safetensors, not pickle)
├── config.json                # architecture — must match the code that loads it
├── tokenizer.json             # or tokenizer.model + vocab
├── tokenizer_config.json
├── special_tokens_map.json
└── inference_metadata.json    # everything needed to reproduce and serve
```

`inference_metadata.json` should record at minimum:

```json
{
  "model_name": "indicpass-hin-v1",
  "created_at": "2026-01-01T00:00:00Z",
  "languages": ["hin"],
  "direction": "roman_to_native",
  "max_input_length": 64,
  "max_output_length": 64,
  "git_commit": "<sha of the training code>",
  "dataset": {
    "source": "aksharantar",
    "revision": "<hub sha>",
    "train_records": 0
  },
  "metrics": { "test_accuracy": 0.0, "test_cer": 0.0 },
  "framework": { "torch": "2.5.1", "transformers": "4.47.1" }
}
```

The `git_commit` and dataset `revision` fields are the ones that matter most.
Without them, a model that behaves oddly six months from now is unreproducible.

**Transfer** by direct copy, external drive, or a Hugging Face model repo
(private if the data licence requires it). Not through Git.

**Rules of thumb**

- Weights and tokenizer travel together. A model with the wrong tokenizer fails
  in ways that look like a bad model rather than a bad load.
- Prefer `safetensors` over `.bin` — no arbitrary code execution on load.
- Keep the bundle self-contained. The development PC should need nothing but
  the directory and `base.txt`.
- Version by directory name (`-v1`, `-v2`). Never overwrite a bundle that has
  been evaluated.

---

## 6. Adding things

### A language

Add a block to `config/languages.yaml` with `unicode_ranges` and
`dataset_codes`, add the code to `default_targets`, add an alias line. No code
changes. `future_candidates` in that file lists the remaining Aksharantar codes.

### A dataset source

Add a block under `sources:` in `config/dataset.yaml` with `repo_id`,
`match_patterns` and `field_map`. Then:

```bash
python scripts/inspect_dataset.py --source <name> --remote --list-files
python scripts/download_datasets.py --source <name> --plan-only
```

A non-Hugging-Face source needs a loader in `src/indicpass/hub.py`.

### A preprocessing rule

Edit `preprocessing:` in `dataset.yaml`, check the effect with `--dry-run`, then
re-run with `--force`. Raw data is untouched, so this is always reversible.

---

## 7. Ordering of phases

Deliberately sequential. Each phase's output is the next one's input, and
skipping ahead means building on data nobody has looked at.

1. **Foundation and dataset pipeline** — done.
2. **Aksharantar: inspect, download, preprocess, validate** — next.
3. **Data analysis** — length distributions, ambiguity rates, coverage per
   language. Decides tokenizer and model sizing. Notebooks in `notebooks/`.
4. **Tokenizer** — trained on processed data.
5. **Model + training** — training PC. Baseline first, one language, small.
6. **Sentence-level and code-mix handling** — needs data Aksharantar does not
   have; may need `data/synthetic/`.
7. **Backend API** — loads a bundle from `models/final/`.
8. **Frontend.**

Do not start step 5 before step 4 exists, and do not start step 4 before
`validate_dataset.py` passes.

---

## 8. Troubleshooting

**`ConfigError: Could not locate the IndicPass project root`** — run from the
project root, or set `INDICPASS_ROOT`.

**`ModuleNotFoundError: indicpass`** — run scripts as
`python scripts/<name>.py` (which bootstraps `sys.path`), or
`pip install -e .`. For notebooks, the editable install is easiest.

**Indic script shows as boxes in the terminal** — a font issue, not a data
issue. Check the JSONL file in an editor; the files are written with
`ensure_ascii=False` so they are readable directly. On Windows PowerShell,
`$env:PYTHONIOENCODING = "utf-8"` helps.

**A script hangs at a prompt in automation** — pass `--yes`. Without a TTY and
without `--yes`, prompts decline rather than block, so a hang means something
else.

**Out of memory during preprocessing** — use `--languages` to process one at a
time, or `--limit` for a smaller run.
