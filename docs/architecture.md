# Architecture

How IndicPass is put together, and why. This document covers what exists today
(the dataset pipeline) and the shape of what comes next (tokenizer, model,
serving), so later phases have somewhere to slot in.

---

## 1. The problem

IndicPass converts Romanized or code-mixed Indic text into native script:

```
"namaste kaise ho"     ->  "नमस्ते कैसे हो"
"vanakkam epdi iruka"  ->  "வணக்கம் எப்படி இருக்க"
"mujhe ek meeting hai" ->  "मुझे एक meeting है"      (English left alone)
```

That is three problems wearing one coat, and it is worth naming them separately
because they need different data and different solutions:

| Sub-problem | Question | Status |
| --- | --- | --- |
| **Transliteration** | What is `namaste` in Devanagari? | Aksharantar covers this directly |
| **Language identification** | Is this Hinglish or Tanglish? | needs its own signal; user-selected at first |
| **Code-mix detection** | Is `meeting` English or a Romanized Indic word? | needs code-mixed corpora, not in Aksharantar |

Phase 1 solves none of them — it builds the ground the first one stands on. The
transliteration lexicon is the foundation; the other two are layered on later.

---

## 2. Layers

```
                    ┌──────────────────────────────┐
                    │  Frontend (later)            │
                    │  text in -> native script    │
                    └──────────────┬───────────────┘
                                   │ HTTP
                    ┌──────────────▼───────────────┐
                    │  Backend / inference (later) │
                    │  loads models/final/<bundle> │
                    └──────────────┬───────────────┘
                                   │
        ┌──────────────────────────▼──────────────────────────┐
        │  Model + tokenizer (later, trained on training PC)  │
        └──────────────────────────┬──────────────────────────┘
                                   │ trained on
        ┌──────────────────────────▼──────────────────────────┐
        │  data/processed/  standardized JSONL                │
        └──────────────────────────┬──────────────────────────┘
                                   │ produced by
   ┌───────────────────────────────▼────────────────────────────────┐
   │  Dataset pipeline  (THIS PHASE)                                │
   │  download -> inspect -> preprocess -> validate                 │
   └───────────────────────────────┬────────────────────────────────┘
                                   │ reads
        ┌──────────────────────────▼──────────────────────────┐
        │  data/raw/  immutable downloads                     │
        └─────────────────────────────────────────────────────┘

   Everything above is driven by  config/*.yaml  and shares  src/indicpass/
```

---

## 3. Why config-driven

Every path, language, threshold and dataset identifier lives in `config/`. No
script contains a literal path or a hardcoded language list.

This is not decoration. It buys three specific things:

1. **Two machines, one repository.** The development PC and the training PC
   check out the same code. Absolute paths would break one of them; relative
   paths resolved against a discovered project root do not.
2. **Changing scope is a config edit.** Adding Bengali means adding a block to
   `languages.yaml`, not touching five scripts. `future_candidates` in that
   file already lists the codes.
3. **Experiments are diffable.** Changing a split ratio or a quality threshold
   shows up as a one-line diff attached to the run, not as an argument someone
   half-remembers typing.

### The three files

| File | Owns |
| --- | --- |
| `project.yaml` | Paths, seed, logging, confirmation behaviour |
| `languages.yaml` | Target languages, ISO codes, scripts, Unicode ranges, aliases |
| `dataset.yaml` | Sources, field mappings, preprocessing rules, splits, validation thresholds |

`src/indicpass/config.py` loads all three, resolves the project root by walking
up for `pyproject.toml` + `config/project.yaml` (overridable with
`INDICPASS_ROOT`), and refuses any absolute path found in `paths:` — a guard
against someone "fixing" a path locally and breaking the other machine.

---

## 4. The shared package

`src/indicpass/` holds everything the scripts have in common. The scripts stay
thin: argument parsing, orchestration, and printing.

| Module | Responsibility |
| --- | --- |
| `config.py` | Load YAML, resolve paths, model `Language`, normalise language aliases |
| `records.py` | The standard `Record`, stable ids, hash-based split assignment, JSONL I/O |
| `script_utils.py` | Unicode normalisation, script-membership ratios, Roman detection |
| `hub.py` | Hugging Face listing, size estimation, selective download, safe zip extraction |
| `logging_utils.py` | Console (rich) + rotating file logging, progress bars, byte formatting |
| `cli.py` | Shared argparse flags, startup, `.env` loading, confirmation prompts, error handling |
| `tokenizer.py` | Character vocabularies, special tokens, save/load |
| `metrics.py` | Edit distance, CER, exact match |
| `seeding.py` | Seeds, device selection, RNG state capture/restore |
| `data.py` | PyTorch `Dataset`, collate, `DataLoader` |
| `model.py` | BiLSTM encoder, attention, LSTM decoder, greedy decoding |
| `trainer.py` | Training loop, evaluation, checkpoints |

The last three import torch at module level and therefore need
`requirements/ml.txt`; everything above them runs on `base.txt` alone. That
split is deliberate — the dataset pipeline must stay usable, and testable, on a
machine that never trains. `pytest` skips the 47 training tests rather than
failing them when torch is absent.

Scripts import `_bootstrap` first, which puts `src/` on `sys.path`. That is why
`python scripts/download_datasets.py` works in a fresh clone with no install
step. `pip install -e .` also works and makes `_bootstrap` a no-op.

`train.py` and `predict.py` import torch *inside* `main()`, so `--help` still
works — and gives a useful message about installing `ml.txt` — on a machine
without it.

---

## 5. The standard record

Every upstream dataset is flattened to one shape before anything else sees it:

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

| Field | Why it is there |
| --- | --- |
| `record_id` | Content hash — deduplication, split assignment, tamper detection |
| `language` | ISO 639-3; the training target and the routing key at inference |
| `script` | ISO 15924; lets validation check the target without a language lookup |
| `source_text` | Romanized / code-mixed input |
| `target_text` | Native-script output |
| `dataset_source` | Which dataset — makes it possible to drop or weight one source later |
| `subsource` | Which sub-corpus within it; optional |
| `split` | `train` / `validation` / `test` |

### Why `subsource` exists and why it is optional

Aksharantar is not one corpus. Its records carry a `source` column naming the
sub-corpus they came from — `Dakshina` (human-curated), `Wikidata`, `AK-Freq`
(frequency-mined) — and those differ in quality. Discarding that label at
preprocessing time would mean re-downloading and re-processing to act on it
later; keeping one short string per record makes "train without AK-Freq" a
filter instead of a rebuild.

It is excluded from `REQUIRED_FIELDS` because not every dataset distinguishes
sub-corpora, and because records written before the field existed must still
validate. `Record.from_dict` fills it with `""`, never `None`.

**It is excluded from `record_id` on purpose.** Provenance is not identity: the
same pair appearing in two sub-corpora is one pair and must collapse to one
record. Including it would silently break deduplication across sub-corpora and
invalidate every previously computed id. A test pins this.

**`record_id` is a hash of `(language, source_text, target_text)` and nothing
else.** Because it does not depend on file position, load order or timestamp:
the same pair gets the same id on both PCs and on every re-run. Two things
follow from that, and both matter:

- **Deduplication is exact and order-independent.**
- **Splits are assigned by hashing the id, not by shuffling.** A record's split
  is a property of its content. Appending new data does not reshuffle existing
  records between train and test, and no seed needs to travel between machines
  for the partition to match.

The fields are joined with `\x1f` (unit separator) before hashing, so
`("hi", "ab")` and `("hia", "b")` cannot collide.

---

## 6. Script validation

The failure mode that quietly ruins a transliteration dataset is a "native"
column that is not actually in the native script: Latin left in place, mojibake
from a bad decode, or one language's rows filed under another.

`script_utils.script_ratio()` measures it. For each character it asks whether
the codepoint falls inside the language's declared Unicode ranges, and returns
the fraction that do.

Two details make the number trustworthy:

- **Neutral characters are excluded.** Joiners (ZWJ/ZWNJ, structurally required
  inside Indic conjuncts), digits, punctuation and spaces are skipped entirely
  rather than counted as failures.
- **No significant characters means `0.0`, not `1.0`.** An empty string or a
  row of punctuation scores zero. "No evidence" must never read as "valid",
  or junk rows sail through.

`detect_language()` uses the same measurement to guess a script. It cannot
separate languages that share one (Hindi and Marathi are both Devanagari),
which is why the pipeline always trusts the dataset's own label over it.

---

## 6a. Split overlap: why it is measured per pair

Validation tracks which splits each source spelling appears in, using a bitmask
packed alongside the ambiguity flag in the cross-record index. Bits are
assigned by position in `config.split_names`, so they stay nameable — which is
what makes per-pair reporting possible rather than one undifferentiated
"leakage" number.

The distinction matters because two overlaps that look identical in a combined
count mean completely different things:

- **train ↔ validation, train ↔ test** — the model is being scored on
  something it trained on. Scores are inflated and the evaluation is invalid.
  Hard gates at zero.
- **validation ↔ test** — no training data is involved. The model saw neither
  set, so both scores are honest; the two evaluation sets are simply a little
  correlated. Reported, not gated.

This is not hypothetical. Aksharantar's Hindi split is clean train-to-eval
(0 and 0) but shares 138 spellings between validation and test. A single
combined gate at zero would reject a dataset that has no contamination
whatsoever — the failure would be in the metric, not the data.

Any threshold set to `null` is measured and reported without gating, which is
the general mechanism this uses.

---

## 7. Data flow and immutability

```
Hugging Face Hub
      │  download_datasets.py  (selective, confirmed, manifest written)
      ▼
data/raw/<source>/                          ← IMMUTABLE
      │  inspect_dataset.py  (read-only; peeks inside zips without extracting)
      │  preprocess_dataset.py  (reads, never writes here)
      ▼
data/processed/<source>/<lang>/<split>.jsonl
      │  validate_dataset.py  (read-only)
      ▼
results/reports/validation_report_*.{json,md}
```

`data/raw/` being immutable is a hard rule. Preprocessing is not destructive —
if a cleaning rule turns out to be wrong, the fix is to change
`config/dataset.yaml` and re-run, not to re-download 20 GB.

Two manifests carry provenance across machines:

- `data/raw/<source>/download_manifest.json` — repo revision, exact file list
  and sizes. Enough to reproduce a raw corpus byte for byte.
- `data/processed/preprocess_manifest.json` — the full preprocessing config
  used, plus per-language kept/dropped counts by reason.

Both are small and are the one thing under `data/` that Git tracks.

---

## 8. Scaling decisions already made

Aksharantar's Hindi portion alone runs to millions of pairs, which rules out a
few otherwise-obvious implementations:

| Decision | Reason |
| --- | --- |
| Preprocessing streams to one open file handle per split | Buffering a language in memory would need gigabytes |
| Deduplication stores 64-bit ints, not hex strings | Hundreds of MB saved at several million records |
| Validation packs cross-record state into one int→int dict | Keyed by string, overlap detection alone would exceed RAM |
| Zip archives are read in place, never extracted to inspect | Avoids doubling disk use just to look at a sample |
| Split assignment hashes instead of shuffling | No need to hold the dataset in memory to partition it |

---

## 9. The training layer

Built. Full detail in [training.md](training.md); the shape, in brief:

### Tokenizer (`src/indicpass/tokenizer.py`)
Character-level, with separate source and target vocabularies — the two sides
share no characters, so a joint vocabulary would only give the decoder classes
it can never legally emit. Subword tokenization was rejected: transliteration
*is* character rewriting, and SentencePiece would add a dependency and
unpredictable fragmentation of rare spellings for no accuracy.

Two invariants: vocabularies are fitted on the **training split alone**, and
ordering is deterministic (frequency descending, ties by codepoint, never set
iteration). The first keeps evaluation honest; the second is what makes a
checkpoint's embedding matrix meaningful on another machine.

Vocabularies are embedded in the checkpoint, not referenced by path — a model
and its tokenizer are one unit.

### Model (`src/indicpass/model.py`)
Word-level seq2seq: BiLSTM encoder → Bahdanau attention → LSTM decoder, ~9M
parameters at the default size. Attention is not optional here; transliteration
is close to monotonic character alignment, and a fixed-size context vector
forces a 30-character word through one bottleneck.

Per-language vs. one multilingual model with a language token remains an
experiment to run, not a decision to make on paper. Hindi first.

### Metrics (`src/indicpass/metrics.py`)
CER primary, exact match secondary. This follows directly from §6a's sibling
finding: 13.33% of Romanized spellings have more than one attested target, so
exact match measures which variant the corpus recorded as much as it measures
correctness. Best-checkpoint selection uses validation CER.

### Sentence handling (`src/indicpass/pipeline/`) — not built
Aksharantar is word-level; user input is not. A sentence needs tokenising into
words, each word classified (English / Romanized Indic / punctuation), the
Indic ones transliterated, and the result reassembled with original spacing.
The classifier needs code-mixed data that Aksharantar does not provide — this
is the gap `data/raw/other/` and `data/synthetic/` exist to fill.

### Serving (`src/indicpass/api/`) — not built
Loads a bundle from `models/final/`, exposes transliteration over HTTP. Runs on
the development PC, CPU only. `scripts/predict.py` already does the loading and
decoding part from the command line.

---

## 10. Extension points

**Add a language.** Add a block to `languages.yaml` with its Unicode ranges and
dataset codes, add the code to `default_targets`. No code changes.
`future_candidates` lists the remaining Aksharantar codes.

**Add a dataset source.** Add a block to `dataset.yaml` with `repo_id`,
`match_patterns` and a `field_map`. The field map lists candidate upstream
column names per standard field, so a source with different column names needs
no code. A non-Hugging-Face source needs a loader in `hub.py`.

**Change preprocessing.** Edit `preprocessing:` in `dataset.yaml` and re-run.
Raw data is untouched, so this is always safe.

**Change quality gates.** Edit `validation.thresholds`. The script exits
non-zero on a breach, so it can gate a training run or a CI job.
