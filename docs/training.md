# Training

The Hindi transliteration baseline: a character-level sequence-to-sequence
model written directly in PyTorch. No modelling framework sits on top of it,
because the whole architecture is about 250 lines and a framework would only
hide the parts worth reading.

```
    "namaste"                       Romanized input
        |
        v
  character ids                     src/indicpass/tokenizer.py
        |
        v
  embedding -> BiLSTM encoder       src/indicpass/model.py
        |
        v
  Bahdanau attention                (masked at PAD)
        |
        v
  LSTM decoder -> vocabulary
        |
        v
    "नमस्ते"                          native script
```

---

## 1. Tokenizer

`src/indicpass/tokenizer.py`

Character-level, with **separate source and target vocabularies**. Hindi needs
roughly 40 Roman symbols and 130 Devanagari ones; the two sides share no
characters, so keeping them apart means the decoder's softmax covers only
characters it could legally emit.

A subword tokenizer would have to be trained, would fragment rare spellings
unpredictably, and would add a dependency — for a task that is character
rewriting by definition.

### Special tokens

Fixed ids in every vocabulary this project ever builds:

| Id | Token | Role |
| ---: | --- | --- |
| 0 | `<PAD>` | Padding. Ignored by the loss and by attention. |
| 1 | `<BOS>` | Decoder start symbol. |
| 2 | `<EOS>` | Generation stops here. |
| 3 | `<UNK>` | A character not seen while fitting. |

`<PAD>` is id 0 deliberately: a zero-filled tensor is then already a padded
batch, and `padding_idx=0` needs no explanation. `IGNORE_INDEX` is the same
value under a name that says what it does at the loss call site.

### Two rules that are not negotiable

**Vocabularies are fitted on the training split alone.** A character that
appears only in validation or test must arrive at evaluation time as `<UNK>`,
exactly as an unseen character would in production. Fitting on all splits
leaks, and quietly flatters every metric. Enforced by `train.py`, which fits
from `train_pairs` before the validation set is even loaded, and tested by
`test_characters_only_in_held_out_data_are_absent_from_the_vocabulary`.

**Ordering is deterministic.** Characters are sorted by descending frequency,
ties broken by codepoint. Never by set iteration. A checkpoint's embedding
matrix is meaningless if the same corpus can produce two different id
assignments.

### Interface

```python
tokenizer = TransliterationTokenizer.fit(pairs)   # train split only
ids  = tokenizer.encode_source("namaste")         # ... <EOS>
ids  = tokenizer.encode_target("नमस्ते")            # <BOS> ... <EOS>
text = tokenizer.decode_target(ids)
tokenizer.save(path); TransliterationTokenizer.load(path)
```

---

## 2. Dataset and batching

`src/indicpass/data.py`

The whole split is read into memory as `(source, target)` string pairs, and
nothing else. Hindi's train split is 270 MB on disk, but almost all of that is
JSON syntax and the five fields training does not use; keeping two text fields
costs roughly 150 MB and buys random access, which shuffling needs. Streaming
would save a hundred megabytes and cost a JSON parse per item on every epoch,
in the dataloader's hot path.

Encoding happens per item rather than up front — a dict lookup per character,
cheaper than holding 1.3M pairs of int lists.

`collate_batch` pads with `PAD_ID` and returns a `Batch` carrying:

- `source`, `target` — `(batch, time)`, batch-first
- `source_lengths` — true lengths, **kept on the CPU** because
  `pack_padded_sequence` requires that
- `source_texts`, `target_texts` — the original strings, so CER is computed
  against what the record actually said rather than a re-decode of its ids

Padding is handled in three places and none of them are optional: the loss
ignores it via `ignore_index`, the encoder never sees it because the sequence
is packed, and attention masks it to `-inf` before the softmax.

---

## 3. Model

`src/indicpass/model.py`

| Component | Choice |
| --- | --- |
| Encoder | Bidirectional LSTM, 2 layers, packed input |
| Attention | Bahdanau (additive), masked at PAD |
| Decoder | LSTM, 2 layers, input-feeding |
| Output | Linear over the target vocabulary |

At the default 256-dim embedding / 512-dim hidden configuration this is
**17,187,904 parameters** — roughly 66 MB of fp32 weights. The training
process needs several times that for activations and Adam's optimizer state,
which is what the batch-size table in the README is really sizing.

**Attention is the part that is not optional.** Transliteration is close to
monotonic character alignment — `janamdivas` → `जन्मदिवस` consumes the source
left to right — and a fixed-size context vector forces a 30-character word
through one bottleneck. Attention lets the decoder look straight at the source
position it is rewriting, which is why this converges in far fewer epochs than
a plain encoder-decoder.

### The alignment contract

`forward()` returns logits of shape `(batch, target_len - 1, vocab)`, aligned
with `target[:, 1:]`. The caller supplies the shift, so there is exactly one
place in the codebase where that off-by-one can live.

This matters more than it looks. A model trained on a mis-shifted target
learns to predict the character it was just handed, and **still shows a
falling loss curve** — it just cannot generate. `test_model.py` asserts the
shape contract directly, and the overfit test would fail loudly if it broke.

---

## 4. Metrics

`src/indicpass/metrics.py`

**Character Error Rate is primary.** 13.33% of Romanized spellings in this
corpus map to more than one attested Devanagari form (see
[dataset_pipeline.md](dataset_pipeline.md#hindi-transliteration-ambiguity)),
so a model can produce a perfectly good transliteration that is not the string
this record happens to hold. Exact match scores that as total failure; CER
scores it as the characters it actually differs by.

CER is computed **corpus-wide** — total edit distance over total target length
— not as a mean of per-example rates. A three-character word getting one
character wrong is a 33% per-example rate; averaging those lets short words
dominate. Summing first weights every character equally, which is what
"character error rate" means.

Empty targets are defined explicitly rather than left to divide by zero:
empty-and-empty scores 0.0, empty-with-a-prediction is clamped to 1.0 rather
than the unbounded value the textbook formula gives.

**Exact match is reported but never decides anything.** `Trainer` selects
`best.pt` on validation CER.

---

## 5. Trainer

`src/indicpass/trainer.py`

| Feature | Detail |
| --- | --- |
| Optimizer | AdamW |
| Gradient clipping | `gradient_clip` (default 1.0) |
| Scheduler | `ReduceLROnPlateau` on validation CER |
| Teacher forcing | `teacher_forcing_ratio` (default 1.0) |
| Checkpoints | `best.pt` (lowest val CER) and `last.pt`, every epoch |
| Early stopping | `early_stopping_patience` epochs without improvement |
| Device | auto-detected; CPU fallback |

**Validation is never teacher-forced.** `evaluate()` greedy-decodes from
`<BOS>` with no access to the gold prefix. A teacher-forced CER would be
measured against inputs the model will not have at inference time — a number
that looks good and means nothing.

That honesty has a cost worth knowing about: greedy decoding runs one step per
output character with no parallelism across time, so evaluating all 6,307
validation records is slow. On CPU it dominates the epoch — a measured 2,000-record
epoch took 261 s, most of it evaluation. On a GPU the balance flips. If epochs
feel evaluation-bound, set `eval_max_batches` to cap it; the resulting CER is
computed on a fixed prefix of the validation set, so it stays comparable
between epochs.

### Checkpoint contents

Enough to resume or to run inference, with no sibling files required:

```
model_state, model_config, optimizer_state, scheduler_state,
epoch, best_cer, history, training_config,
tokenizer (both vocabularies, embedded), rng_state
```

The tokenizer is embedded rather than referenced by path. A checkpoint that
depends on a neighbouring file is one careless copy away from being unusable,
and the vocabularies are a few kilobytes.

---

## 6. Configuration

`config/training/`, deliberately two files rather than a directory full of
near-duplicates. Subset stages are CLI overrides, not new configs.

### `hindi_debug.yaml` — the correctness test

500 records, no dropout, 30 epochs. **Run this before any real training.**

```bash
python scripts/train.py --config config/training/hindi_debug.yaml
```

Two details are deliberate: `dropout: 0.0`, because the run is *trying* to
overfit and regularisation would fight the signal; and
`evaluate_on_train_subset: true`, because the question is "can this model
memorise what it was shown", which validation data cannot answer.

### `hindi_baseline.yaml` — the real run

Defaults: batch 128, embedding 256, hidden 512, 2+2 layers, dropout 0.2,
LR 1e-3, 15 epochs, early stopping after 3.

---

## 7. Scale-up plan

Do not jump to the full dataset. Each stage answers a different question, and
each is the same config file with `--max-train-records` applied — no data is
duplicated on disk, because the processed splits are deterministic and "the
first N" is a stable subset.

| Stage | Records | Question | Command |
| ---: | ---: | --- | --- |
| 1 | 500 | Is the model correct at all? | `--config config/training/hindi_debug.yaml` |
| 2 | 10,000 | Does the pipeline hold up at speed? | `--max-train-records 10000 --name hindi_10k --epochs 5` |
| 3 | 100,000 | Is the architecture actually learning? | `--max-train-records 100000 --name hindi_100k --epochs 8` |
| 4 | 1,299,143 | The baseline. | `--config config/training/hindi_baseline.yaml` |

Stages 2–4 all use `hindi_baseline.yaml`.

---

## 8. The overfit test

`tests/test_training_sanity.py`, and the debug config as an end-to-end version.

This is the most valuable test in the suite. A seq2seq with a mis-shifted
target, a broken attention mask, or a loss ignoring the wrong index will still
show a falling training loss — it learns *something*, just not the task. The
one thing such a model cannot do is drive CER on a handful of examples to near
zero.

**Result on 500 real Hindi records** (`hindi_debug.yaml`, CPU, ~5 minutes):

| Epoch | Train loss | CER | Exact match |
| ---: | ---: | ---: | ---: |
| 1 | 3.3070 | 0.7893 | 0.0000 |
| 3 | 1.6686 | 0.4217 | 0.0780 |
| 8 | 0.4175 | 0.1004 | 0.6280 |
| 12 | 0.1083 | 0.0152 | 0.9400 |
| 16 | 0.0338 | 0.0012 | 0.9980 |
| **19** | **0.0140** | **0.0000** | **1.0000** |
| 30 | 0.0036 | 0.0000 | 1.0000 |

Perfect memorisation by epoch 19. **The pipeline is correct.**

If this ever fails, stop — full training is pointless until it passes. Likely
causes, roughly in order of how often they are the answer:

1. Target shift wrong — logits not aligned with `target[:, 1:]`
2. Loss not ignoring `PAD` (`ignore_index`)
3. Attention mask inverted, so the model attends only to padding
4. Learning rate far too high (loss oscillates) or too low (loss barely moves)
5. `source_lengths` moved to the GPU — `pack_padded_sequence` needs CPU lengths

---

## 9. Reproducibility

`src/indicpass/seeding.py` seeds Python's `random`, NumPy, PyTorch CPU and
PyTorch CUDA from one number, and `capture_rng_state` / `restore_rng_state`
carry that state through a checkpoint so a resumed run continues the same
stream rather than restarting it.

**What is guaranteed:** the same command, on the same machine, with the same
seed, produces the same numbers. That is the useful property — it makes an
experiment comparable with the one before it.

**What is not:** bit-exact reproducibility across machines. cuDNN picks RNN
algorithms by benchmarking the local GPU. Forcing deterministic kernels
(`deterministic: true`) makes LSTM training substantially slower for a
guarantee that breaks anyway on different hardware. It is off by default;
turn it on for a run that must be exactly repeatable and accept the cost.

Note that dataset preprocessing *is* bit-exact across machines — record ids
and split assignment derive from content hashes alone. The non-determinism
discussed here is training's, not the data's.

---

## 10. Inference

```bash
python scripts/predict.py \
    --checkpoint runs/hindi_baseline_v1/checkpoints/best.pt \
    --text "namaste"
```

Greedy decoding. The checkpoint carries its own tokenizer, so nothing else is
needed to run it.

The model is **word-level**, so a multi-word line is split on whitespace and
each word transliterated independently. That is a limitation of the training
data — Aksharantar is a word-level corpus — not of the script. Sentence-level
handling needs segmentation, context, and code-mix detection on top; see
[architecture.md](architecture.md).

Beam search and top-k decoding are not implemented. Given the one-to-many
mapping in this corpus, top-k is the more informative evaluation and is the
natural next addition — but greedy is the honest baseline.
