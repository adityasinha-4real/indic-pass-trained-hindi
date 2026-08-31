# Dataset pipeline

Four scripts, run in order. Each does one thing, reports what it did, and says
what to run next. All of them run from the project root:

```
inspect (remote)  ->  download  ->  inspect (local)  ->  preprocess  ->  validate
```

Common flags on every script:

| Flag | Meaning |
| --- | --- |
| `--languages` / `-l` | Language codes, 639-1 codes or names. Default: the five targets |
| `--source` / `-s` | Dataset source from `dataset.yaml`. Default: `aksharantar` |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--yes` / `-y` | Skip confirmation prompts (required for non-interactive runs) |

---

## 1. `inspect_dataset.py`

Read-only, always. Local files are opened read-only and zip archives are peeked
into without extracting, so it is safe to point at `data/raw/` at any time.

### Remote mode — before downloading anything

```bash
python scripts/inspect_dataset.py --remote
python scripts/inspect_dataset.py --remote --list-files
python scripts/inspect_dataset.py --remote --json > results/reports/aksharantar_meta.json
```

Queries the Hugging Face API for repository metadata only — a few kilobytes of
JSON, never dataset content. Reports:

- revision SHA, last modified, licence, gated status
- total file count and total bytes
- a breakdown by file extension and by top-level directory (this is how you
  learn the repository's real layout)
- per target language: which files matched, how many bytes, and what share of
  the repository that represents

This is the step that answers "how big is this actually, and can I take just
the part I need?" before committing to a transfer.

### Local mode — after downloading

```bash
python scripts/inspect_dataset.py --local --samples 5
python scripts/inspect_dataset.py --local --path data/raw/other
```

Walks the raw directory and, per file, reports size, detected format, record
count, inferred columns and real sample records. Understands JSON Lines, JSON
arrays, CSV/TSV, Parquet, and zip archives (listing members and sampling from
the first text member, without extracting).

With no mode flag, it inspects locally if raw data exists and remotely if not.

---

## 2. `download_datasets.py`

Fetches raw data into `data/raw/`. **Nothing transfers until a plan has been
printed and confirmed.**

```bash
python scripts/download_datasets.py --list-languages   # no network at all
python scripts/download_datasets.py --plan-only        # metadata only, then stop
python scripts/download_datasets.py --languages hin tam
python scripts/download_datasets.py --languages hin --yes
```

### How selective download works

`dataset.yaml` gives each source a list of `match_patterns` containing a
`{code}` placeholder:

```yaml
match_patterns:
  - "{code}.zip"
  - "{code}/*"
  - "*/{code}.zip"
```

For each requested language the placeholder is filled with that language's
`dataset_codes` entry and fnmatch'ed against the repository's **real** file
listing. Only matched paths are passed to `snapshot_download` as
`allow_patterns`, so nothing outside the resolved list is ever fetched.

If the patterns match nothing, the script stops and tells you to look at the
actual listing rather than guessing:

```
python scripts/inspect_dataset.py --remote --list-files
```

Patterns can be overridden per run with `--pattern '{code}.zip'`.

### Safety rails

| Rail | Behaviour |
| --- | --- |
| Plan printed first | Per-language file counts and byte totals before any transfer |
| Confirmation required | `--yes` to skip; a non-TTY without `--yes` declines rather than hanging |
| `--max-bytes` | Aborts above N GiB (default 25) — a typo cannot start a huge download |
| `--plan-only` | Resolve and print, then stop |
| Revision pinning | Downloads pin the resolved SHA, so a re-run gets the same bytes |
| Zip-slip guard | Archive members that would write outside the target are refused |

### Output

```
data/raw/aksharantar/
├── hin.zip                      # as published
├── extracted/hin/               # unpacked (skip with --no-extract)
└── download_manifest.json       # revision, file list, sizes, timestamp
```

The manifest is small and Git-tracked. It is what lets the training PC
reproduce the development PC's exact raw corpus.

---

## 3. `preprocess_dataset.py`

Raw → standardized JSONL. **`data/raw/` is opened read-only and never written
to**, so a wrong cleaning rule costs a re-run, not a re-download.

```bash
python scripts/preprocess_dataset.py --dry-run       # full stats, writes nothing
python scripts/preprocess_dataset.py
python scripts/preprocess_dataset.py --languages hin --limit 5000 --force
```

### Output layout

```
data/processed/
├── aksharantar/
│   ├── hin/{train,validation,test}.jsonl
│   └── tam/{train,validation,test}.jsonl
└── preprocess_manifest.json
```

Per-language, per-split files make it cheap to load one language or one split
without reading the rest. Empty splits produce no file.

### What it does, in order

1. **Find the language's raw files** by matching the dataset code against path
   components and filename tokens (`hin/hin_train.json` and `hin.zip` both hit).
2. **Read records** from JSONL, JSON arrays, CSV/TSV, or directly out of zip
   archives without extracting.
3. **Map fields.** `field_map` in `dataset.yaml` lists candidate upstream column
   names per standard field, tried in order and matched case-insensitively:
   ```yaml
   field_map:
     source_text: ["english word", "english_word", "source", "src", "roman"]
     target_text: ["native word", "native_word", "target", "tgt", "native"]
     subsource:   ["source", "origin"]
   ```
   An upstream column rename is a config edit, not a code change.

   `subsource` captures the sub-corpus a record came from (Aksharantar:
   `Dakshina`, `Wikidata`, `AK-Freq`). Note that `source` is a candidate for
   both `source_text` and `subsource` — if the value resolves to the same text
   as the source or target, it is treated as a text column and the subsource is
   left empty rather than recorded as bogus provenance.
4. **Clean.** Unicode NFC, whitespace collapsed, source lowercased. Native text
   is left alone — Indic scripts are unicameral.
5. **Filter,** counting every drop by reason (see below).
6. **Assign a split.** The dataset's own split if the filename says so
   (`hin_valid.json` → `validation`), otherwise by hashing the record id.
7. **Deduplicate** on `(language, source_text, target_text)`.
8. **Stream to disk** — one open handle per split, written as input is read.

### Drop reasons

Every rejected record is counted and reported. Silent data loss shows up as a
number, not a mystery.

| Reason | Meaning |
| --- | --- |
| `missing_field` | No usable source or target column |
| `empty_after_cleaning` | Empty once normalised and trimmed |
| `source_length` / `target_length` | Outside the configured bounds |
| `source_not_romanized` | Source side is not Roman script |
| `target_wrong_script` | Target is not in the language's declared script |
| `duplicate` | Already seen this exact pair |

`--dry-run` reports everything a real run would, and writes nothing: records
discovered, records accepted, every drop reason with counts and percentages,
counts by split, counts by subsource, and representative samples of what was
dropped for each reason.

Real output from the Hindi dry run (Aksharantar revision `e418c1fc`):

```
  lang          read        kept   kept%    dropped        train validation       test
  hin      1,315,624   1,315,562 100.00%         62    1,299,143      6,307     10,112

  Dropped by reason
    reason                          count    % of read
    duplicate                          61      0.0046%
    target_wrong_script                 1      0.0001%
    TOTAL DROPPED                      62      0.0047%

  Accepted by subsource
    subsource                        kept    % of kept    dropped
    IndicCorp                     958,605       72.87%          9
    Samanantar                    154,090       11.71%         20
    Existing                      131,771       10.02%          2
    Dakshina                       31,293        2.38%          2
    Wikidata                       24,983        1.90%         29
    AK-Freq                        12,806        0.97%          0
    AK-NEI                          1,188        0.09%          0
    AK-NEF                            826        0.06%          0
```

A large `target_wrong_script` count is a signal, not just noise — check the
field mapping and the language's Unicode ranges before accepting it. The
sample block under each reason shows the actual records, which usually makes
the cause obvious at a glance.

### Reproducibility

Same raw files + same `dataset.yaml` = byte-identical output. Nothing depends
on file order, timestamps or a random seed, because record ids and split
assignment both derive from content alone.

### Refusing to overwrite

Existing processed files are not overwritten without `--force`. Use `--dry-run`
to see what a config change would do first.

---

## 4. `validate_dataset.py`

The quality gate. Reads `data/processed/`, writes a report, exits non-zero on a
threshold breach — so it can gate a training run or a CI job.

```bash
python scripts/validate_dataset.py
python scripts/validate_dataset.py --languages hin --split test
python scripts/validate_dataset.py --no-report --quiet   # exit code only
```

### Checks

| Check | Catches |
| --- | --- |
| Missing fields, nulls, empty strings | Truncated or malformed writes |
| Duplicate `record_id` | Deduplication that did not work |
| `record_id` vs. content | A file edited by hand after processing |
| Target script ratio | Latin left in an Indic column; one language filed under another |
| Source Roman ratio | Native script in the input column |
| NFC normalisation | Strings that look identical but will never match |
| Language vs. directory | Records in the wrong folder |
| **Split overlap** | The same source spelling in more than one split — see below |
| Ambiguous sources | One Roman spelling with several native forms |

Ambiguous sources are *reported, not penalised* — one Roman spelling mapping to
several native forms is normal in transliteration (`namaste` / `namaskar`), but
the count is worth watching.

### Split overlap, measured per pair

Overlap is measured between each **pair** of splits, as a fraction of unique
source spellings, because the pairs do not mean the same thing:

| Pair | What it means | Gated? |
| --- | --- | --- |
| `train_validation` | An evaluation item the model trained on — contamination | **yes, at 0.0** |
| `train_test` | Same, for the test set — contamination | **yes, at 0.0** |
| `validation_test` | Two evaluation sets share vocabulary; no training data involved | no, reported only |

Contamination inflates every evaluation number that follows and is invisible
unless you look for it, so both train pairs are hard gates at zero. A
validation/test overlap is a different animal: the model never saw either set
during training, so the scores are still honest — it only means the two
evaluation sets are slightly correlated. Failing a run over it would reject
good data.

Aksharantar Hindi is the motivating case. Its train split is clean against both
evaluation splits (0 and 0), but 138 spellings are shared between validation
and test — 0.0128% of unique sources. Under a single combined gate at zero,
that dataset would fail validation despite having no contamination at all.

`validation_test` is still *gateable* — set
`max_validation_test_overlap_ratio` to a number in `dataset.yaml`. `null`
(the default) means measure and report only.

Console output:

```
  Split overlap (shared source spellings)
  lang   pair                      count        ratio  gate
  hin    train_validation              0     0.000000  GATED at 0
  hin    train_test                    0     0.000000  GATED at 0
  hin    validation_test             138     0.000128  reported only
```

### Thresholds

From `validation.thresholds` in `dataset.yaml`:

```yaml
thresholds:
  max_null_ratio: 0.0
  max_duplicate_ratio: 0.001
  min_target_script_ratio: 0.95
  min_source_ascii_ratio: 0.95
  min_records_per_language: 1000
  max_train_validation_leakage_ratio: 0.0   # contamination -- hard gate
  max_train_test_leakage_ratio: 0.0         # contamination -- hard gate
  max_validation_test_overlap_ratio: null   # reported, not gated
```

A threshold that is `null` or absent is measured and reported but never fails
a run. That is the mechanism behind the ungated `validation_test` metric, and
it works for any threshold in the list.

### Reports

Written to `results/reports/`:

- `validation_report_<UTC timestamp>.json` — full detail, machine-readable
- `validation_report_<UTC timestamp>.md` — human-readable summary with samples
- `validation_report_latest.json` — stable filename for tooling

Console output:

```
  lang      records    dupes   script    roman    leak     status
  ---------------------------------------------------------------
  hin             6   0.0000   1.0000   1.0000       0       FAIL
  tam             3   0.0000   1.0000   1.0000       0       FAIL

  hin threshold breaches:
    - min_records_per_language: 6 < 1000
```

---

## Hindi transliteration ambiguity

A property of the corpus, measured on the processed Hindi splits. It is not a
defect in the data and nothing in the pipeline tries to remove it, but it
changes how the model must be evaluated, so it is documented here rather than
discovered later.

| Measure | Value |
| --- | --- |
| Unique Romanized sources | 1,080,299 |
| Sources with more than one attested target | 143,972 |
| **Ambiguity rate** | **13.33%** |

One Romanized spelling can map to several different native-script forms. There
is no single correct Devanagari string for a given Roman input, because the
mapping genuinely is one-to-many:

- Romanization is lossy. `kal` is both `कल` (yesterday/tomorrow) and `काल`
  (time); nothing in the Roman form distinguishes the vowel length.
- People spell inconsistently. `dhanyavaad`, `dhanyavad` and `dhanyawad` are
  all written for `धन्यवाद`, and the reverse holds too.
- The corpus is largely web-mined. IndicCorp and Samanantar together supply
  84.6% of the Hindi pairs and carry the spelling variation of real text.

The spread is heavily skewed. Most ambiguous sources have exactly two forms
(102,318 of them), but the tail is long: `employees` has 65 distinct attested
Devanagari spellings, `responsibility` 43, `establishment` 41.

### What this means for evaluation

**Exact-match accuracy understates quality, and by an unknown amount.** A model
that outputs a perfectly good transliteration is scored as wrong whenever the
reference happens to be a different valid spelling. On roughly one input in
seven, exact match is measuring which variant the corpus recorded rather than
whether the model transliterated correctly.

**Character Error Rate is the primary metric.** CER scores a
correct-but-different output as the one or two characters it actually differs
by, instead of as a total failure. `indicpass.metrics` implements it as corpus
CER — total edit distance over total target length — and
`Trainer` selects the best checkpoint on validation CER, never on exact match.

**Exact match is still reported**, because it is what someone typing into a
transliteration box experiences, and because a widening gap between the two
numbers is itself informative. It is simply not what decisions are made on.

**Top-k evaluation is the natural next step** and is not implemented yet. With
a one-to-many mapping, "is the reference among the model's top 5 outputs" is a
fairer question than "is it the single argmax". That needs beam search;
baseline v1 decodes greedily.

### What the pipeline deliberately does not do

**Ambiguous targets are not collapsed.** No majority vote, no
highest-`subsource`-priority filter, no dropping of minority variants. The
baseline trains on the corpus as it is, for two reasons: collapsing would
discard real spelling variation that a transliteration system should arguably
learn, and doing it before there is a baseline to compare against would make
the effect unmeasurable.

**Provenance is preserved so that this stays an option.** Every record keeps
its `subsource`, so a later experiment can weight human-curated `Dakshina`
pairs above mined `IndicCorp` ones, or restrict training to a cleaner subset,
without re-running acquisition. That is the reason the field exists.

---

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success (validation: all thresholds met) |
| 1 | Operational failure, or a validation threshold breached |
| 2 | Configuration error |
| 130 | Interrupted (Ctrl-C) |

---

## Troubleshooting

**"No files matched for: hin, tam"** — the repository layout differs from
`match_patterns`. Run `inspect_dataset.py --remote --list-files`, read the real
paths, and update `match_patterns` in `dataset.yaml`.

**Everything dropped as `missing_field`** — the upstream column names are not
in `field_map`. Run `inspect_dataset.py --local --samples 5`; it prints the
actual column names. Add them to the candidate lists.

**Everything dropped as `target_wrong_script`** — either source and target
columns are swapped in `field_map`, or the language's `unicode_ranges` are
wrong. `inspect_dataset.py --local --samples 5` will show which.

**Gated dataset error** — accept the terms on the dataset page while signed in,
then put a read token in `.env` as `HF_TOKEN`.

**Confirmation prompt in a script or CI** — pass `--yes`. Without a TTY and
without `--yes`, the prompt declines rather than hanging.
