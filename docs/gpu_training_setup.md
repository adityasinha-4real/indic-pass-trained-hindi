# Training IndicPass on an NVIDIA GPU laptop

Setting up this project on a second machine with a CUDA GPU, and training the
Hindi baseline on it. Written for an RTX 3050 laptop; the batch-size table is
the only part specific to that card.

The project can arrive two ways -- cloned from GitHub, or unzipped from a
folder someone sent you. Both converge at [§4](#4-set-the-batch-size).

Sections 1-3 are setup. Sections 4-6 are training.

- [0. Preflight](#0-preflight)
- [1. Pick a delivery route](#1-pick-a-delivery-route)
- [2. Route A -- clone and rebuild](#2-route-a--clone-and-rebuild)
- [3. Route B -- receive a zip](#3-route-b--receive-a-zip)
- [4. Set the batch size](#4-set-the-batch-size)
- [5. Train in stages](#5-train-in-stages)
- [6. Use the trained model](#6-use-the-trained-model)
- [7. Troubleshooting](#7-troubleshooting)

---

## 0. Preflight

Four checks. Two of them decide settings used later, so note the answers.

| Check | Command | What you need |
| --- | --- | --- |
| Git | `git --version` | Any recent version |
| Python | `python --version` | **3.11 or 3.12** -- see the warning below |
| GPU and VRAM | `nvidia-smi` | The memory figure: **4 GB or 6 GB** sets the batch size |
| Free disk | `Get-PSDrive C` / `df -h .` | At least **8 GB** |

### Use Python 3.11 or 3.12, not the newest release

This project was developed on Python 3.14, but only the **CPU** build of
PyTorch was ever installed on it. CUDA wheels routinely lag new Python
releases by months.

That matters because of how the failure presents. If no CUDA wheel exists for
your Python version, pip does not error -- it falls back to the CPU build.
Training then runs correctly and produces a real model, just 10-20x slower,
with nothing in the output explaining why. The verification in
[§2 step 3](#3-install-cuda-pytorch-first-then-the-requirements) is what
catches it.

### Disk budget

| Item | Size | Notes |
| --- | ---: | --- |
| Source checkout | 1.3 MB | 62 files |
| Python environment | ~4 GB | Mostly the CUDA PyTorch build |
| Raw dataset | 221 MB | 33 MB archive plus extraction |
| Processed JSONL | 274 MB | The three splits |
| Checkpoints, per run | ~420 MB | `best.pt` + `last.pt`, weights plus AdamW state |

---

## 1. Pick a delivery route

Both end in the same place. The difference is whether the dataset travels over
the network from Hugging Face, or over a USB stick.

| | Route A -- clone | Route B -- zip |
| --- | --- | --- |
| Transfer | ~221 MB from Hugging Face | ~275 MB from the sender |
| Extra time | ~15 min preprocessing | none |
| Git history | yes | only if `.git` is included |
| Best when | the connection is decent | the connection is slow or metered |

Either is safe. Preprocessing is deterministic: record ids are content hashes
and split assignment derives from those hashes, so rebuilding from the same
upstream revision produces byte-identical files. This was verified by
comparing SHA256 across all three splits after a forced re-run. Route A and
Route B yield the same data.

---

## 2. Route A -- clone and rebuild

Roughly 25 minutes end to end, most of it downloading.

### 1. Clone and enter

```bash
git clone https://github.com/adityasinha-4real/indic-pass.git
cd indic-pass
```

### 2. Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If PowerShell blocks the activation script, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window
first. It applies to that window only.

### 3. Install CUDA PyTorch first, then the requirements

The order matters. `requirements/ml.txt` asks for plain `torch`, and pip
resolves that to the CPU build from PyPI. Installing the CUDA build from
PyTorch's own index beforehand means the later install sees the requirement
already satisfied and leaves it alone.

```bash
python -m pip install --upgrade pip

# CUDA build FIRST -- match the CUDA version nvidia-smi reported
python -m pip install torch --index-url https://download.pytorch.org/whl/cu124

# then the project's own dependencies
python -m pip install -r requirements/dev.txt
python -m pip install -r requirements/ml.txt
```

Verify CUDA actually engaged before going further:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

```text
2.5.1+cu124
True
```

`False` on a machine that has an NVIDIA GPU means the installed build is
CPU-only. Go back to Python 3.11 or 3.12, delete `.venv`, and redo this step.
Training on CPU by accident is the most likely way to waste a day here.

### 4. Run the tests before touching data

```bash
python -m pytest -q
```

Expect **184 passed**. **137 passed** means `ml.txt` did not install -- the 47
training tests skip themselves rather than fail. Anything actually failing:
stop, do not edit source, and report the output.

### 5. Download, preprocess, validate

Three scripts, in order. The download fetches one 33 MB archive, not the full
695 MB corpus, and prints a plan before transferring anything.

```bash
python scripts/download_datasets.py --languages hin
python scripts/preprocess_dataset.py --languages hin
python scripts/validate_dataset.py  --languages hin
```

Expect these counts -- they are the figures this repository was verified
against:

| Split | Records |
| --- | ---: |
| train | 1,299,143 |
| validation | 6,307 |
| test | 10,112 |
| **total** | **1,315,562** |

Train/validation and train/test overlap are hard-gated at zero; the script
exits non-zero if either is breached. A report lands in `results/reports/`.

Route A is done. Continue at [§4](#4-set-the-batch-size).

---

## 3. Route B -- receive a zip

### Sender: build the archive

Never include `.venv`. It is roughly 1 GB, hard-wired to the sending machine's
paths, and on the development PC it holds the **CPU-only** PyTorch build --
copying it would both bloat the transfer and guarantee CPU training. The same
goes for `runs/`: those are CPU debug checkpoints, of no use on a GPU.

```powershell
# 1. stage a clean copy (robocopy exit codes 0-7 mean success)
$src   = "E:\Sem 7 Project 1\IndicPass"
$stage = "$env:TEMP\indicpass-transfer"

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
robocopy $src $stage /E /XD .venv runs .git __pycache__ .pytest_cache .ruff_cache /XF *.pyc

# 2. drop the raw dataset -- only the processed splits are needed to train
Remove-Item "$stage\data\raw\aksharantar\extracted" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$stage\data\raw\aksharantar\hin.zip"   -Force -ErrorAction SilentlyContinue
Remove-Item "$stage\data\raw\aksharantar\.cache"    -Recurse -Force -ErrorAction SilentlyContinue

# 3. compress
Compress-Archive -Path "$stage\*" -DestinationPath "$HOME\Desktop\indicpass.zip" -Force

# 4. sanity check the size
(Get-Item "$HOME\Desktop\indicpass.zip").Length / 1MB
```

Expect **60-120 MB** zipped, from ~275 MB on disk -- JSONL compresses well. A
zip near a gigabyte means `.venv` got included; check the exclusions and redo.

Keep `data/raw/aksharantar/download_manifest.json`. It is small and it pins
which upstream revision produced the data.

To send source only (~1.3 MB) and let the receiver rebuild the dataset, add
`data` to the exclusion list and have them run [§2 step 5](#5-download-preprocess-validate):

```powershell
robocopy $src $stage /E /XD .venv runs .git data __pycache__ .pytest_cache .ruff_cache
```

### Receiver: unpack and set up

```powershell
Expand-Archive indicpass.zip -DestinationPath "$HOME\indicpass"
cd "$HOME\indicpass"

python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install exactly as in [§2 step 3](#3-install-cuda-pytorch-first-then-the-requirements):

```bash
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r requirements/dev.txt
python -m pip install -r requirements/ml.txt

python -c "import torch; print(torch.cuda.is_available())"   # must be True
python -m pytest -q                                          # 184 passed
```

Skip download and preprocessing -- the processed splits are already present.
Run validation instead, which re-derives every count and overlap check from
the files themselves:

```bash
python scripts/validate_dataset.py --languages hin
```

If the counts differ from the table in §2 step 5, the transfer was incomplete.
Re-zip rather than trying to patch it.

---

## 4. Set the batch size

The one setting that depends on the specific card. Everything else in
`hindi_baseline.yaml` is already sized for a laptop GPU.

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
```

| Card | Batch size | Hidden dim | Flag |
| --- | ---: | ---: | --- |
| RTX 3050 4 GB | 64 | 512 | `--batch-size 64` |
| RTX 3050 6 GB | 128 | 512 | none -- 128 is the config default |
| Still out of memory | 32 | 512 | `--batch-size 32` |

On `CUDA out of memory`, halve the batch size before touching anything else.
Leave `hidden_dim` alone: changing it makes results incomparable with every
run recorded so far, and the memory saving is smaller than the batch lever.

---

## 5. Train in stages

Four runs, each a gate on the next. A mistake that surfaces in three minutes
at stage 1 costs a day at stage 4.

### Stage 1 -- the overfit gate (~3 min)

500 records, dropout deliberately set to zero. The model must reach
essentially perfect scores on its own training data. This is a correctness
test, not a quality test: it fails loudly if the target shift, the attention
mask or the loss reduction is wrong.

```bash
python scripts/train.py --config config/training/hindi_debug.yaml
```

Measured on CPU, for reference:

```text
loss 3.3070 -> 0.0036    CER 0.7893 -> 0.0000    exact 0.0000 -> 1.0000
```

**If CER does not fall near zero, do not continue to stage 2.** A model that
cannot memorise 500 examples will not learn 1.3 million. Report the loss curve
instead.

### Stage 2 -- 10k records, pipeline shakeout

First contact with the real validation split, and the run that yields a
trustworthy per-epoch timing.

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml \
  --max-train-records 10000 --name hindi_10k --epochs 5 --batch-size 64
```

Note the seconds per epoch. Multiply by ~130 to estimate a full-dataset epoch.

### Stage 3 -- 100k records

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml \
  --max-train-records 100000 --name hindi_100k --epochs 8 --batch-size 64
```

Validation CER should be clearly better than stage 2. Flat or worse means
something is wrong -- investigate before committing to the full run.

### Stage 4 -- the full baseline

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml --batch-size 64
```

**Runtime here is an estimate, not a measurement.** No RTX 3050 timings exist
for this project; every measurement so far is from a CPU-only machine.
Extrapolating, expect roughly **30-60 minutes per epoch**, so **8-15 hours**
for the 15-epoch schedule. Treat that as an order of magnitude and replace it
with the real figure from stage 2.

`early_stopping_patience: 3` may end the run before 15 epochs. Keep the laptop
on mains power with sleep disabled.

### Resuming an interrupted run

Every run writes `last.pt` beside `best.pt`, carrying optimizer, scheduler,
epoch and RNG state. Resuming continues the run rather than restarting it.

```bash
python scripts/train.py --config config/training/hindi_baseline.yaml --resume
```

---

## 6. Use the trained model

Checkpoints embed their own tokenizer, so a checkpoint works anywhere the code
does -- there is no side file to keep in sync.

```bash
python scripts/predict.py \
  --checkpoint runs/hindi_baseline_v1/checkpoints/best.pt \
  --text "namaste kaise ho bharat"
```

```text
नमस्ते कैसे हो भारत
```

`--json` emits machine-readable output; `--device cpu` runs without the GPU.

Do not judge the model on exact string matches alone. 13.33% of Romanized
spellings in this corpus map to more than one attested Devanagari form (see
[dataset_pipeline.md](dataset_pipeline.md)), so a perfectly good
transliteration is often not the string a given record happens to hold. That
is why the best checkpoint is selected on CER, and why exact match is reported
but not optimised for.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `cuda.is_available()` is False | CPU wheel installed, usually no CUDA build for that Python version | Python 3.11/3.12, delete `.venv`, reinstall with the `--index-url` step |
| `137 passed`, not 184 | `ml.txt` never installed | `pip install -r requirements/ml.txt` |
| `CUDA out of memory` | Batch too large for the card | Halve `--batch-size`; do not change the model |
| Training says data is missing | Download/preprocess not run, or the zip was incomplete | The error names the three commands to run, in order |
| `Activate.ps1` blocked | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Epochs feel evaluation-bound | 6,307 validation records, greedily decoded every epoch | Set `eval_max_batches` in the config to cap it |

### Things not to do

- Do not copy `.venv` between machines. Build it fresh on each.
- Do not hand-edit generated JSONL. Regenerate it instead.
- Do not delete `download_manifest.json` or `preprocess_manifest.json`; they
  pin provenance.
- Do not commit datasets or checkpoints. `.gitignore` already excludes them.
- Do not change `hidden_dim` to save memory. It makes runs incomparable.

---

Related: [training.md](training.md) for what the model and trainer actually
do, [dataset_pipeline.md](dataset_pipeline.md) for the data and its ambiguity,
[development_workflow.md](development_workflow.md) for the two-PC setup.
