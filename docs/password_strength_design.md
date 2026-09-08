# Password strength design

How IndicPass turns a password into an estimated number of guesses, where every
number in that estimate comes from, and what the estimate is not.

The engine is `src/indicpass/password/`; every constant it uses lives in
`config/password.yaml`. Nothing here runs the transliteration model: the
model's entire contribution arrived offline, as the dictionary file, which is
what makes scoring a lookup and a benchmark reproducible from a committed
artefact rather than from a model's mood.

## How to read this document

Every quantitative claim is tagged. The tags are not decoration — the point of
the milestone was to stop the three from blurring together.

| Tag | Meaning |
| --- | --- |
| **[measured]** | Computed from data in this repository. The command that produces it is named, and its output is in `results/reports/`. |
| **[heuristic]** | A modelling choice with a stated rationale but no experiment establishing it is correct. Often calibrated by a sweep, which shows *sensitivity*, not correctness. |
| **[assumption]** | An unverified premise about attacker behaviour. Stated so it can be attacked. |

An unlabelled statement is a description of what the code does.

---

## 1. Dictionary sources

IndicDict is built by `scripts/build_indicdict.py` from the Aksharantar Hindi
corpus, using the trained transliterator `indicpass-hin-v1` to produce a native
form for every Romanized spelling.

**Pipeline.**

```
Romanized Hindi vocabulary (train + validation + test)
          |  ascii lower-case letters only, length 3..16
          v
trained transliterator, greedy decode
          |  script check; agreement with the corpus's attested forms
          v
external frequency join, through the NATIVE form
          |
          v
IndicDict  ->  data/dictionaries/indicdict_hin.jsonl
               data/dictionaries/indicdict_hin.meta.json
```

**Provenance tiers.** Aksharantar records which subsource each pair came from.
Those are grouped into four tiers, best first:

| Tier | Subsources | What it is |
| --- | --- | --- |
| `human_romanized` | Dakshina | Human-written romanizations — the spellings real Hindi speakers type, which is exactly the password threat model. |
| `curated_entities` | Wikidata, AK-NEI, AK-NEF | Named entities: given names, surnames, places. Flagged `named_entity` so the meter can say "this is a name" separately from "this is a word". |
| `curated_other` | Existing, AK-Freq | Pre-existing transliteration corpora folded into Aksharantar. |
| `mined` | IndicCorp, Samanantar | Automatically mined from monolingual and parallel corpora. Largest, least precise. |

The tier ordering is **not** a frequency ranking. It is an ordering by how the
pair was produced. **[assumption]** Human-written romanizations are more likely
to appear in an attacker's Romanized-Indic wordlist than machine-mined pairs.

**Why all three splits, not just train.** This builds a *wordlist*, not a
model. Nothing is fitted, and nothing is later evaluated against the
transliteration splits, so the usual reason to hold data back does not apply —
while the cost is real: `bharat` and `krishna` live in the 1% validation and
test splits, and a Hindi password dictionary missing those two would be a worse
instrument for no gain. The held-out transliteration evaluation
(`results/reports/test_eval_hin_v1.json`) was run before this and is unaffected
by it.

**Current build.** **[measured]**

| | |
| --- | ---: |
| Entries | 297,747 |
| Model-verified (prediction is among the corpus's attested forms) | 211,752 (71.1%) |
| Rejected: empty prediction / wrong script | 0 / 0 |
| Mined spellings dropped by the 120,000 cap | 767,350 |

| Tier | Entries | Ranked | Unranked | Fallback offset |
| --- | ---: | ---: | ---: | ---: |
| `human_romanized` | 30,400 | 13,437 | 16,963 | 40,966 |
| `curated_entities` | 25,005 | 1,747 | 23,258 | 57,929 |
| `curated_other` | 122,342 | 23,612 | 98,730 | 81,187 |
| `mined` | 120,000 | 2,170 | 117,830 | 179,917 |

Reproduce with `python scripts/build_indicdict.py --languages hin`.

---

## 2. Frequency methodology

The guess model needs one number per word: how far down an attacker's wordlist
it sits. Getting that number honestly was the central problem of this
milestone.

### 2.1 Aksharantar supplies no frequency

Three checks, all reproducible against `data/raw/aksharantar/extracted/hin/`:

| Candidate | Finding | Verdict |
| --- | --- | --- |
| The `score` column | **[measured]** Present on all 1,299,155 rows but non-null **only** on the 956,190 IndicCorp rows, with values in [-0.35, 0]. It is a mining log-likelihood. | Not frequency. A model score. |
| The `AK-Freq` subsource | **[measured]** Not frequency-ordered: its first entries are words like *maitrologist*, *phwcs*. The name refers to how the subsource was assembled upstream, not to an ordering in the shipped file. | Not frequency. |
| Record order | Each (romanized, native) pair appears once; the corpus is deduplicated, so repetition counts nothing. | Not frequency. |

Reinterpreting any of these as word frequency would be fabrication. None is.

### 2.2 External candidates considered

| Source | What it measures | Hindi | Reproducible rank | Licence | Decision |
| --- | --- | --- | --- | --- | --- |
| **wordfreq 3.1.1** | Zipf: log10(occurrences per billion tokens) of the native-script word, over Wikipedia, OSCAR web text, Twitter, Reddit | Yes, 26,653 words (`small` list; no `large` list ships for Hindi) | Yes — frozen dataset, pinned version | Apache-2.0 package; aggregated corpora under their own terms | **Chosen** |
| Raw IndicCorp token counts | Genuine corpus token frequency, and the largest Hindi corpus available | Yes | Yes, in principle | Open, but tens of GB | Rejected: the download and processing cost is out of proportion to a wordlist that only needs a ranking, and nothing in the repository already holds it |
| Dakshina romanization lexicon | Attestation counts of *romanizations* by human annotators | Yes | Yes | CC BY-SA 4.0 | Rejected: it measures how a native word is spelled in Latin script, not how common the word is. Useful for a *future* romanization-variant model, not for ranking a wordlist |

**Why wordfreq is defensible for this purpose.** Attackers order wordlists by
corpus frequency; that is what zxcvbn's own dictionaries are. Using the same
kind of quantity for the Indic side is what makes the comparison a comparison
of *lexicons* rather than of two unrelated ranking schemes.

**What it is not.** **[assumption]** Corpus word frequency is a proxy for the
order in which an attacker tries Romanized Indic words. It is not password
frequency. Nobody has published a Romanized-Indic password leak with counts;
if one existed it would be strictly better than this. zxcvbn's English side
carries the same limitation and documents it the same way.

**Provenance recorded.** wordfreq 3.x is deliberately frozen — its author
stopped updating it in 2024 — which makes it a stable citation but means it
reflects pre-2022 text. The exact identifier `wordfreq-3.1.1/hi/small`, the
semantics string, the corpora list and the licence are written into
`indicdict_hin.meta.json` and into every report header.

### 2.3 The join

wordfreq is keyed on Devanagari; IndicDict is keyed on Roman spellings. The
bridge is the native form:

1. the transliterator's own prediction for that spelling; failing that,
2. the corpus's attested native forms for it, best (commonest) first.

Which route matched is recorded per entry as `frequency_matched_via`, because
the two are not equally trustworthy: route 1 is model-mediated and inherits the
model's CER of 0.108; route 2 is corpus-mediated. **[measured]** 26,647 entries
matched via the prediction and 14,319 via an attested form.

`frequency.use_attested_forms: false` disables route 2, making the join
strictly model-mediated.

### 2.4 Coverage, and what happens without it

**[measured]** 40,966 of 297,747 entries (13.8%) carry an observed frequency.
The rate is itself informative, and is what one would predict if the tiers mean
what they claim:

| Tier | Frequency coverage |
| --- | ---: |
| `human_romanized` | 44.2% |
| `curated_other` | 19.3% |
| `curated_entities` | 7.0% |
| `mined` | 1.8% |

Named entities are under-covered because a general-text frequency list is thin
on surnames. The mined tier is almost entirely uncovered, which is consistent
with it holding corpus artefacts rather than words.

Entries with no observed frequency keep `frequency: null` and `rank: null`.
**No value is substituted for them.** They are priced by the fallback in §3.2,
and the meter reports which policy it used on every match.

---

## 3. Ranking methodology

An entry's cost is its position in the attacker's wordlist, produced by exactly
one of two policies. `IndicDict.guess_position()` is the single place they meet,
and it returns the policy alongside the number.

### 3.1 `observed_rank` — the evidence path

Every entry with a frequency is sorted by descending frequency and numbered
`1 .. R`. `g = rank`.

Ties are broken by `(length, spelling)`. Ties are common — two romanizations of
one native word share its frequency — and the order has to be total or the file
would not round-trip.

**Ranks are recomputed at load time, never trusted from the file.** An ablation
that loads a subset must re-rank against the entries it actually holds, or every
estimate in that run would cite a wordlist that was not used.

### 3.2 `tier_fallback` — the policy path

No frequency observed. The word is priced by its provenance tier:

```
g = offset(t) + (unranked_size(t) + 1) / 2
offset(t) = R + sum of unranked_size of every better tier
```

**[heuristic]** Within a tier the order is unknown, so a uniform draw is the
honest model, and `(n+1)/2` is the expected position of a uniformly random item
among `n`.

**[assumption]** The fallback band sits *after* the entire ranked band: an
attacker holding frequency data exhausts the words they can order before
reaching the ones they cannot.

This is a **stated policy, not a measured quantity**, and it is where the
estimate is least trustworthy. The meter emits a warning naming the number of
fallback-priced hits in any result that relies on one.

### 3.3 What the schema keeps separate

Section 3 of the milestone brief: a model score is not a word frequency. The
entry schema keeps four things apart and never collapses them:

| Field | What it is |
| --- | --- |
| `frequency` | Observed corpus frequency of the native form, on the provider's scale. `null` means *not observed*; it never means zero. |
| `rank` | 1-based position in this dictionary's descending-frequency ordering. `null` iff `frequency` is `null`. |
| `frequency_source` | The table it came from. Set iff `frequency` is set — a bare number would be uninterpretable. |
| `model_confidence` | **Deliberately unpopulated.** The transliterator is decoded greedily with no calibrated probability, so there is no confidence score to record. The field exists so that nothing is tempted to put a mining score or a tier position here instead. `model_verified` carries the real, observed signal: whether the prediction agrees with the corpus. |

`variant_count` is a real count of attested native forms. It is not a frequency
and is not used in scoring.

### 3.4 What ranking changed

**[measured]** From `results/reports/guess_model_sensitivity.md`, the
`no_frequency` arm (Milestone 1 pricing, tiers only) minus the shipped
configuration, in mean log10 guesses:

| english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +0.04 | +0.42 | +0.44 | +0.46 | +0.46 | +0.63 | +0.00 |

Frequency ranking lowered Indic estimates by roughly half an order of magnitude
and left the English and random controls alone. Concretely: `bharat` was priced
at 42,904 guesses by its tier and is priced at **41** by its measured rank; भारत
is genuinely one of the commonest words in Hindi. `merabharat` — two of the
commonest words in the language — scored 4 of 4 under tier pricing and now
scores 1.

---

## 4. Exact and substring matching

The matcher offers candidate spans; the segmentation search decides which win.
A dictionary hit is exact: a span matches only if its lower-cased form is
literally a key. Being made of Latin letters is not enough.

### 4.1 Why match classes exist

**[measured]** `results/reports/indicdict_coverage_hin.md`. The probability
that a random lower-case string of length L is one of the dictionary's keys,
computed exactly as (keys of that length) / 26^L:

| L | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keys | 6,999 | 24,967 | 65,834 | 70,278 | 29,925 | 28,855 |
| P(hit) | 0.398 | 0.055 | 0.0055 | 2.3e-4 | 3.7e-6 | 1.4e-7 |

Two of every five three-letter strings are in the dictionary. A three-letter
hit is close to no evidence at all; a seven-letter hit is strong evidence. The
match classes keep that difference visible to the guess model.

### 4.2 The classes

| Class | When | Penalty |
| --- | --- | ---: |
| `EXACT_WORD` | The span is the whole password, as written. | 1.0 |
| `TRANSFORMED_WORD` | The span is the whole password once a case change is undone. | 1.0 |
| `SUBSTRING_WORD` | A proper substring, length ≥ `min_substring_length`. | 1.0 |
| `FRAGMENT` | A proper substring shorter than that. | 10.0 |

The penalty multiplies the wordlist position. `min_substring_length: 4` is set
where a hit stops being more likely than not to be an accident.

A short word that *is* the password is `EXACT_WORD`, not `FRAGMENT`: `maa` on
its own has no coincidence to correct for.

**[heuristic]** The class penalty. The segmentation search already charges for
splitting a password, so this only corrects for the residual fact that a short
entry in a 298k wordlist is often a corpus artefact rather than a word anyone
would attack with. The value 10.0 is a round number chosen from the sweep in
§11, not derived.

### 4.3 The `namaste` case, honestly

The milestone brief asked that `namaste` prefer `WORD(namaste)` over
`? + WORD(maste)` **when `namaste` is in the dictionary**. That conditional is
the correct formulation and it is enforced by
`tests/test_meter.py::test_a_word_beats_a_fragment_of_itself`, which builds a
fixture holding both spellings.

Two things must be said plainly about the real dictionary:

1. **`namaste` is not in it.** It is absent from Aksharantar's Hindi split at
   source (§12). So the fragment reading was never competing with a whole-word
   reading; it was competing with "this is 7 unexplained characters".
2. **The fragment reading disappeared for a different reason than the one the
   brief anticipated.** `namaste` now scores as pure brute force (10^7), not
   through `maste`, because the brute-force cardinality changed from 26 to 10
   (§6) and 10^7 is now cheaper than `2! × 10^2 × 238,832`. The fragment
   penalty did not cause this. Attributing it to the penalty would be wrong.

Suppressing fragment matches outright would have made this *worse*, not better:
when the whole word genuinely is missing, `?? + maste` is a real attack path,
and banning it would overstate the password. That case is pinned by
`test_the_fragment_reading_survives_when_the_word_is_genuinely_absent`.

### 4.4 False matches on random controls

**[measured]** `results/reports/guess_model_sensitivity.md`, 500 deterministic
random strings per cell, seed 42, across three alphabets × five lengths.

| | offered (matcher found a span) | **accepted** (a span won a place in the estimate) |
| --- | ---: | ---: |
| worst cell | 99% | **1.2%** |
| lower-case, length 14 | 99% (mean 5.3 spans) | 1% (mean 0.01) |
| full charset, length 8 | 55% (mean 1.0 spans) | 0% (mean 0.00) |

The dictionary does offer a match inside nearly every random lower-case string.
Almost none survives: the segmentation search rejects a fragment whenever
calling the span unexplained is cheaper, which it nearly always is. **The
matcher being noisy and the estimate being wrong are different things, and only
the second matters.**

The fragment penalty's real effect is here rather than on the estimate:

| Configuration | Worst accepted rate |
| --- | ---: |
| shipped (fragment penalty 10×) | 1.2% |
| fragments priced as words | 3.2% |
| fragments dropped entirely | 0.6% |

---

## 5. The guess-number formula

For a segmentation `S = (m_1 .. m_k)` covering the whole password:

```
G(S) = k! · Π g(m_i)  +  D^(k-1)

guess_number  = min over all S of G(S)
log10_guesses = log10(guess_number)
strength_score = |{ t in thresholds : guess_number >= t }|
```

Everything is computed in log10 space; the products overflow a float long before
a password gets unreasonable.

### 5.1 Every term

| Term | Represents | Attacker behaviour approximated | Status |
| --- | --- | --- | --- |
| `g(word) = position × U × penalty` | Reaching a dictionary word | Walking a frequency-ordered wordlist, trying case variants of each | position: **[measured]** when `observed_rank`, **[heuristic]** when `tier_fallback` |
| `position` | Wordlist index | See §3 | **[measured]** / **[heuristic]** |
| `U` (case variations) | Undoing capitalisation | Try as-is, then the obvious shift | **[heuristic]** — 1 for lower, 2 for Capitalised/UPPER/finaL, `Σ C(n,i)` for genuinely mixed. Identical to zxcvbn's rule, deliberately, so a difference between the estimators is not about capital letters |
| `penalty` (match class) | How much the hit explains | — | **[heuristic]**, §4.2 |
| `k!` | Orderings of k segments | The attacker does not know which piece comes first | **[assumption]**, taken from zxcvbn |
| `D^(k-1)` | Reaching a k-segment structure at all | Enumerating structures before contents | **[heuristic]**, `D = 10,000`, zxcvbn's value |
| `min over S` | The attacker's best case | A password is only as strong as its cheapest explanation | **[assumption]** — and the load-bearing one: it is why adding the Indic dictionary can only ever *lower* an estimate, never raise it |
| digits: `10^n` | An n-digit run | Enumerate all n-digit strings | **[assumption]** |
| year: `high - low + 1` | A 4-digit run inside 1900–2035 | Enumerate the year window, 136 values, not 10,000 | **[heuristic]** — the window is a judgement about which years people use |
| symbols: `33^n` | A symbol run | Enumerate ASCII punctuation | **[assumption]** |
| repeat: `C × n` | `aaaa` | Pick the character, then the length — not `C^n` | **[heuristic]** |
| brute force: `10^n` | An unexplained span | A flat cost per unexplained character | **[heuristic]**, §6 |

**The structure term is added, not multiplied.** It is a floor: a k-piece
explanation cannot cost less than `D^(k-1)` however cheap its pieces are.
Multiplying would make it compound, and a three-piece reading of `sharma@123`
would cost more than calling the last four characters random — the meter would
discard an explanation it had already found.

### 5.2 The search

A dynamic programme over `(position, segment count)`: `best[j][k]` is the
smallest achievable `Σ log10 g(m)` covering `[0, j)` with exactly *k* segments.
`k!` and `D^(k-1)` depend only on *k*, so they are applied once at the end
rather than inside the recurrence — which is why *k* is carried in the state.

A brute-force span is offered for every substring, so the search is never empty
and `max_segmentation_depth` can only ever raise an estimate.

### 5.3 Worked examples

**[measured]** against the current dictionary.

```
bharat        41                                            = 41  guesses  (10^1.62, score 0)
              g(bharat) = rank 41 × 1 variation × 1.0

bharat2024    2! × (41 × 136) + 10,000                      = 21,152        (10^4.33, score 1)
              g(bharat) = 41         [observed_rank]
              g(2024)   = 136        [year window]

merabharat    2! × (213 × 41) + 10,000                      = 27,466        (10^4.44, score 1)
              g(mera)   = 213        [observed_rank, mined tier — provenance
                                      says how it was found, frequency says
                                      how common it is]

krishna123    2! × (3,026 × 1,000) + 10,000                 = 6,062,000     (10^6.78, score 2)

namaste       10^7                                          = 10,000,001    (10^7.00, score 2)
              no dictionary hit survives: the word is absent from the corpus
```

`namaste` is where this model is at its worst. zxcvbn reaches it in **3,847**
guesses because it is in zxcvbn's English wordlist; IndicPass says 10^7. That
gap is coverage (§12), not arithmetic.

---

## 6. Brute-force assumptions

An unexplained span costs `cardinality^length`. The cardinality is
`scoring.bruteforce_cardinality`, either an integer or the string `observed`
(the character classes present: 26 / 36 / 95).

**Set to a flat 10, after measurement.** **[measured]** From the sensitivity
sweep, `observed_cardinality` minus the shipped configuration, mean log10:

| english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +1.03 | +1.12 | +1.34 | +1.15 | +2.49 | +3.23 | **+7.33** |

Under `observed`, IndicPass read **+7.12** log10 above zxcvbn on random
controls — where there is no lexical structure at all, and therefore nothing
the Indic dictionary could possibly have contributed. That entire divergence
was one setting. Left there, the benchmark would have been measuring an
alphabet assumption and reporting it as Indic awareness.

Two reasons for the change, in order of weight:

1. **It holds the assumption equal with the baseline.** zxcvbn charges a flat
   10 per unexplained character. With both estimators on the same rule they
   differ in their lexicon and in nothing else, which is the only way the
   experiment answers its own question. **[measured]** After the change the
   random controls agree: median difference 0.00, 180 of 200 samples within
   tolerance.
2. **It errs in the safer direction.** **[assumption]** The classical
   alphabet-size model assumes an attacker learns nothing from how people pick
   characters, which over-estimates strength — the dangerous direction for a
   meter. A flat per-character cost is deliberately conservative.

`observed` remains available and is reported as an arm of every sensitivity
run. **Whichever policy produced a number must be stated alongside it.**

---

## 7. Mined-tier behaviour

The mined tier is 120,000 of 297,747 entries, capped from 887,350 candidates.
**[measured]** Only 1.8% of it has an observed frequency, so almost all of it is
priced by the fallback — a policy, not a measurement.

In Milestone 1 this was the standing concern: at offset 177,747 a mined hit cost
~238,000 guesses, cheaper than brute-forcing any 4-character span under the
then-current cardinality, so short mined matches fired constantly.

**[measured]** `results/reports/mined_tier_ablation.md`. Dropping the tier
entirely, change in mean log10 guesses:

| Category | All tiers | Without mined | Difference |
| --- | ---: | ---: | ---: |
| english | 7.08 | 7.09 | +0.01 |
| indic_word | 4.35 | 4.36 | +0.00 |
| indic_numeric | 7.87 | 7.90 | +0.03 |
| indic_year | 6.85 | 6.89 | +0.04 |
| indic_symbol | 6.98 | 7.02 | +0.04 |
| mixed | 11.92 | 11.96 | +0.04 |
| random | 11.01 | 11.01 | −0.00 |

Match rates fall by at most 6 percentage points (`indic_year` 48% → 42%).

**Conclusion: the mined tier is not carrying the result.** Its contribution to
every category is under 0.05 log10 — two orders of magnitude smaller than the
lexicon's overall effect of ~0.9 (§11). The Milestone 1 concern was real under
the old configuration and is resolved by two changes acting together: mined
entries that are genuinely common words now get a measured rank (`mera` at 213),
and the ones that are corpus artefacts are pushed past 179,917 in the fallback
band where the brute-force alternative beats them.

No claim in this project rests on mined-tier matches, and none should.

---

## 8. Strength thresholds

The 0–4 score is a transparent transformation of the guess estimate and nothing
else: `score = |{ t in thresholds : guess_number >= t }|`.

| Threshold | Score | Label | Intended reading |
| ---: | :---: | --- | --- |
| — | 0 | Very Weak | Online attack, no rate limiting |
| 10^3 | 1 | Weak | Online attack, with rate limiting |
| 10^6 | 2 | Fair | Offline attack, slow hash |
| 10^8 | 3 | Strong | Offline attack, fast hash |
| 10^10 | 4 | Very Strong | Beyond the above |

**[assumption]** These are a **project scoring convention**, not experimentally
validated security or psychological boundaries. They are placed at the
order-of-magnitude boundaries common password tooling uses so that IndicPass and
the baseline can be compared band for band. They should be recalibrated against
a real attack cost model, and any published score must name the thresholds that
produced it.

They are configurable in `config/password.yaml`. The scale validates its own
input: strictly increasing, positive, and exactly one more label than
thresholds.

**The primary metric is `guess_number`; `log10_guesses` is the primary analysis
scale.** The 0–4 score is for humans and is derived, never fitted.

---

## 9. The zxcvbn baseline

The research question is meaningless without a generic estimator to compare
against.

| | |
| --- | --- |
| Package | `zxcvbn` 4.5.0 (PyPI, `dwolfhub/zxcvbn-python`) |
| Licence | MIT |
| Wordlists | passwords 30,000; english_wikipedia 30,000; us_tv_and_film 19,160; surnames 10,000; female_names 3,712; male_names 983 |
| Adapter | `src/indicpass/password/baseline.py` |

`PasswordStrengthBaseline` is an ABC exposing `estimate(password) ->
BaselineEstimate` with `guesses`, `log10_guesses`, `score`, `patterns`,
`feedback`. `ZxcvbnBaseline` is the only implementation. Nothing zxcvbn-shaped
crosses that boundary: its result carries the password itself and, per match,
the matched substring and the wordlist entry it hit. **Only pattern names cross;
everything else is dropped**, so a benchmark row can say "zxcvbn read this as
dictionary + date" without recording what the date was.

**Why zxcvbn specifically.** IndicPass borrowed its combinatorics — the `k!`,
the additive structure floor, the case-variation rule, and now the brute-force
cardinality. Holding those identical is what makes a difference between the two
attributable to the lexicon.

**[measured]** zxcvbn's wordlists are not Indic but are not innocent of Indic
words: `namaste`, `bharat`, `krishna` and `sharma` all resolve to `dictionary`
matches in it. Pinned by `tests/test_baseline.py`. Any framing that treated
"Indic word" as "invisible to zxcvbn" would be measuring its own assumption.

---

## 10. Benchmark design

`src/indicpass/password/benchmark.py`, run by `scripts/password_benchmark.py`.

**Generated, not collected.** No real password appears anywhere. Every sample is
assembled from committed word banks by a generator seeded from
`evaluation.seed`, so a run reproduces exactly from that integer.

**Nothing reaches disk.** A generated password is still password material —
publishing a list of realistic Indic passwords would be publishing a cracking
wordlist. Rows are keyed on `sample_id` and `category`; the password lives in
memory for the length of a run. Reproducibility comes from the generator plus
the seed, which is what reproducibility actually requires. Enforced by
`tests/test_benchmark.py` and `tests/test_result_schema.py`, which score
distinctive passwords and then search the JSON for every piece of them.

| Category | N | Construction |
| --- | ---: | --- |
| `english` | 200 | Common English password vocabulary, optionally + digits |
| `indic_word` | 200 | A bare Romanized Hindi word |
| `indic_numeric` | 200 | Indic word + 2–5 digits |
| `indic_year` | 200 | Indic word + a year in 1950–2025 |
| `indic_symbol` | 200 | Indic word + symbol (+ digits) |
| `mixed` | 200 | Two lexical pieces, indic/english in both orders, + symbol or digits |
| `random` | 200 | 8–14 characters, three alphabet widths |

Each category draws from its own `Random`, seeded by the corpus seed plus the
category's fixed index, so an ablation over a subset produces the *same*
passwords rather than a differently-shuffled set. Duplicates are dropped within
a category so a repeat cannot be weighted twice.

**The word banks are the instrument, not the answer.** The Indic bank was
written from what a Hindi speaker would plausibly type and deliberately **not**
sampled from IndicDict — sampling the dictionary would guarantee coverage and
measure nothing. The consequence is that many bank words are missing from
IndicDict, and the benchmark reports that rather than avoiding it.

### 10.1 Metrics

Per category: N, mean and median log10 guesses for each estimator, mean and
median strength score, the count of samples where IndicPass is lower / higher /
equal (tolerance 0.05 log10, below which the gap is smaller than either
estimator's modelling error), the mean and median difference, and the number of
0–4 disagreements.

Everything is computed on **log10**, never on guesses. Guess counts span thirty
orders of magnitude; a mean over them is the largest sample and nothing else.

### 10.2 The statistic that answers the question

Reporting only "does IndicPass beat zxcvbn" would be the wrong test. IndicPass
has no common-password wordlist and was never going to win outright on English.

Guessing cost is a minimum over the attacker's options — the same rule the
segmentation search applies within one estimator — so an attacker holding both
wordlists pays `min(IndicPass, zxcvbn)`. **Information added** is that minimum
minus zxcvbn alone: how much cheaper the password becomes once Indic lexical
knowledge is available. It is never positive, and it is zero exactly when
IndicPass found nothing the baseline had not already found.

**A lower estimate is not automatically a more accurate one.** Establishing that
requires a reference attack — a cracking run against a real leak — which this
project does not have. The reports state the direction and the magnitude and
stop there.

---

## 11. Ablation methodology

Every arm is the shipped configuration with exactly one thing changed, scored
over the same corpus in the same run, sharing one baseline and one scale.
Dictionaries are re-ranked from scratch when entries are removed.

| Arm | What it changes |
| --- | --- |
| `no_dictionary` | Empty IndicDict — isolates the lexicon from generic pattern scoring |
| `no_mined_tier` | The mined tier dropped |
| `no_frequency` | Milestone 1 pricing: provenance tier only |
| `observed_cardinality` | Brute force by character class instead of flat 10 |
| `no_substring_matches` | Whole-password dictionary hits only |
| `no_fragment_matches` | Sub-threshold hits dropped instead of penalised |
| `fragment_penalty_1` | Fragments priced identically to real words |
| `min_substring_6` | Substring threshold raised from 4 to 6 |

**[measured]** Effect of the Indic dictionary (A vs B), mean log10 with minus
without:

| english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| −1.18 | −0.86 | −0.79 | −0.91 | −0.93 | −1.82 | **−0.00** |

This is the signature the experiment was designed to detect: a consistent
~0.9 order-of-magnitude reduction on Indic material and **exactly nothing** on
random controls. A lexicon that lowered random strings too would be finding
structure that is not there.

The −1.18 on English is not an error. Aksharantar's `Existing` subsource is a
transliteration corpus, so the Hindi dictionary really does contain
romanizations of English words — §12.

**[measured]** Match-quality arms, mean log10 relative to shipped:

| Arm | english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `no_substring_matches` | +0.56 | +0.07 | +0.79 | +0.91 | +0.93 | +1.82 | +0.00 |
| `no_fragment_matches` | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 |
| `fragment_penalty_1` | +0.00 | −0.00 | −0.03 | −0.01 | −0.01 | −0.02 | −0.03 |
| `min_substring_6` | +0.05 | +0.04 | +0.18 | +0.18 | +0.14 | +0.23 | +0.00 |

Two honest readings:

* **Substring matching does most of the lexical work.** Disabling it costs 1.82
  log10 on `mixed`. The strict "exact matches only" reading of the brief would
  have thrown away most of what the dictionary contributes.
* **The fragment machinery barely affects the estimate.** ≤0.03 log10
  everywhere. It is a defensible safeguard — it cuts the false-acceptance rate
  on random controls from 3.2% to 1.2% (§4.4) — but it is not the fix the
  Milestone 1 symptom appeared to call for. The two things that actually moved
  the numbers were frequency ranking and the brute-force cardinality.

---

## 12. Limitations

Ordered by how likely each is to be mistaken for a result.

**1. Corpus coverage is the ceiling, and it is low.** **[measured]**
`results/reports/indicdict_coverage_hin.md`: 8 of 15 core probe words present
(53.3%), 62 of 163 across the full bank (38.0%). Absent from the corpus *at
source* — not filtered out, not a pipeline bug: `namaste`, `namaskar`,
`dhanyavaad`, `sharma`, `maa`, `dost`, `ghar`, `dil`, `beta`, `raja`, `rani`,
`india`, `hindustan`, `ishq`. Aksharantar is a transliteration benchmark built
from named entities and mined pairs, not a lexicon of what people type. **No
word was added by hand to close this gap**; a dictionary tuned to recognise the
demo would say nothing about the general question. This is the single largest
limitation of the whole approach and the first thing any Indic result should be
read against.

**2. The English control set is contaminated.** **[measured]** 7 of 10 generic
English password words are in the "Hindi" dictionary: `password`, `football`,
`qwerty`, `monkey`, `dragon`, `shadow`, `superman` all have legitimate
Devanagari transliterations in Aksharantar's `Existing` subsource. The English
category is therefore a weaker control than its name suggests, and the −1.18
effect there is partly real coverage rather than pure noise.

**3. 86% of entries are priced by policy, not evidence.** Only 13.8% have an
observed frequency. The tier fallback is a stated, documented rule, but it is
not a measurement, and estimates that rest on it should be read as such. The
meter says so per result.

**4. Frequency is corpus frequency, not password frequency.** **[assumption]**
No Romanized-Indic password leak with counts exists publicly. If one appeared it
would be strictly better than wordfreq for this purpose.

**5. No reference attack model.** Nothing here has been validated against an
actual cracking run. "IndicPass estimates fewer guesses" is a statement about
two models, not about reality. This is the blocker on any accuracy claim.

**6. IndicPass is not a replacement for zxcvbn.** **[measured]** It reads +3.19
log10 above zxcvbn on English passwords because it has no common-password
wordlist at all. The deployable object is `min(IndicPass, zxcvbn)`, not
IndicPass alone.

**7. Transformations beyond case are unmodelled.** Leet substitution
(`n4m4ste`), separators, keyboard patterns and reversal are not implemented in
either estimator. Passwords using them will be over-estimated. (§14's character
model reads `n4m4ste` as an unsupported span, not as a mangled word.)

**8. Hindi only.** One language, one script, one romanization convention.

**9. The estimator is not independent of its baseline.** IndicPass deliberately
shares zxcvbn's combinatorics. That is what makes the comparison clean, and it
also means IndicPass is not an independent confirmation of anything zxcvbn does.

**10. The benchmark word banks are the author's judgement** of plausible
Romanized Hindi password material, not a sample from a real distribution.

---

## 13. Reproducibility

Python 3.14, `requirements/base.txt` (adds `zxcvbn>=4.5.0`, `wordfreq>=3.1.1`)
plus `requirements/dev.txt`. The dictionary build additionally needs
`requirements/ml.txt` for torch.

```bash
# 1. The dictionary. ~35 min on CPU: it decodes 297,747 words.
#    Needs torch; add --no-frequency to reproduce the Milestone 1 artefact.
python scripts/build_indicdict.py --languages hin

#    Without torch, re-annotate an existing build in ~1 min instead:
python scripts/build_indicdict.py --languages hin \
    --reuse-native-forms data/dictionaries/indicdict_hin.jsonl

# 2. Coverage.                 -> results/reports/indicdict_coverage_hin.{json,md}
python scripts/indicdict_coverage.py --languages hin

# 3. Benchmark, ablations and sensitivity, from one scoring pass.
#    -> password_benchmark_hin.{json,md}
#    -> mined_tier_ablation.{json,md}
#    -> guess_model_sensitivity.{json,md}
python scripts/password_benchmark.py --languages hin

# 4. The PCFG (§14). Fits the grammar and samples the guess curve, ~20s.
#    -> data/pcfg/pcfg_hin.json   (47 KiB: the curve, not the grammar)
python scripts/train_pcfg.py --languages hin

# 5. PCFG evaluation: the same 1,400 samples, twelve ablation arms, the
#    targeted cases and the random control. ~4 min.
#    -> pcfg_benchmark_hin.{json,md}
#    -> pcfg_targeted_hin.{json,md}
python scripts/pcfg_benchmark.py --languages hin

# 6. Reference-attack validation (§15). Ranks the same 1,400 samples in a
#    bounded enumeration and scores all three estimators against the result.
#    Six attacker arms, ~2 min.
#    -> reference_attack_hin.{json,md}
python scripts/reference_attack.py --languages hin

# 7. Out-of-lexicon attack validation (§16). The same 1,400 samples against an
#    attacker whose candidates come from a character model instead of a
#    wordlist, so the 872 targets step 6 cannot reach are reachable. Seven
#    arms, bootstrap intervals, and a second process to check byte identity.
#    ~5 min.
#    -> milestone5_oov_attack.{json,md}
python scripts/milestone5_oov_attack.py --languages hin

# 8. One password, interactively, without echo. Prints all three estimators.
python scripts/check_password.py

# 9. Tests.
python -m pytest -q
```

Steps 4 to 7 need neither torch nor a network: the grammar is refitted from the
committed dictionary, and a fingerprint over `(spelling, frequency, tier)`
refuses an artefact that was trained against different data rather than
producing a silently wrong number. Steps 6 and 7 build no wordlist of any kind —
both enumerations are counted, not materialised.

**What pins a result.**

| | |
| --- | --- |
| Model | `indicpass-hin-v1`, held-out test CER 0.108429, exact match 56.18% on 10,112 records |
| Dictionary | `indicdict_hin.meta.json` — tier sizes, offsets, filters, the model that produced the native forms, and the frequency source |
| Frequency | `wordfreq-3.1.1/hi/small`, a frozen dataset; the exact identifier is in every report header |
| Baseline | `zxcvbn` 4.5.0, version recorded in every report header |
| Corpus | `evaluation.seed` (42) + `GENERATOR_VERSION` (1.0), both in every report header |
| PCFG | `data/pcfg/pcfg_hin.json` — the guess curve, every hyper-parameter, the sampler seed, and a SHA-256 fingerprint of the dictionary the grammar was fitted to |
| Reference attack | `ATTACK_VERSION` (1.0) + `reference_attack` in `config/password.yaml` + a SHA-256 fingerprint over the ordered lexicon and the placed rule programme, all three in every report header |
| Config | `config/password.yaml` — every constant the model uses; nothing in `src/indicpass/password/` hardcodes a cost or a threshold |

`GENERATOR_VERSION` must be bumped whenever the generator or a word bank
changes, so a result can never be silently compared against a corpus it was not
run on.

---

---

## 14. The PCFG (Milestone 3)

Sections 1–13 describe an *estimator*: a wordlist position, a few multipliers,
and a combinatorial rule borrowed from zxcvbn. Most of it is tagged
**[heuristic]** above, and honestly so. This section describes a **probability
model** that replaces the guess formula and derives the guess number from the
model instead.

It runs **alongside** the estimator above, not instead of it. `guess_number`
still comes from §5. Whether the PCFG should replace it is a question the
comparison in §14.8 answers, and the answer is no.

> **The PCFG is a model, not a measurement of attacker behaviour.** Nothing in
> this section has been validated against an observed cracking run. Every
> statement below is about what two models say, never about what an attacker
> would actually do.

### 14.1 The grammar

`src/indicpass/password/pcfg/`. A password is a sequence of segments, each from
one of five categories:

```
S       ->  C_1 C_2 ... C_k                     P(k) · Π P(C_i)
C       ->  word | unknown | digits | year | symbols
word    ->  <an IndicDict entry>, cased         P(entry) · P(case | length)
unknown ->  <any Roman spelling>, cased         P_ngram(spelling) · P(case | length)
digits  ->  <n digits>                          P(n) · 10^-n
year    ->  <a year in 1900–2035>               1 / 136
symbols ->  <n symbols>                         P(n) · 33^-n
```

The grammar is deliberately **ambiguous** — a dictionary word also derives
through `unknown`, and `2024` through both `digits` and `year`. The parser takes
the maximum-probability derivation, which is the one an attacker enumerating in
probability order actually arrives by.

Every distribution is normalised, which is the property §5's model lacks and the
reason a guess number can be *counted* rather than asserted.

### 14.2 What is learned, and what is not

This split is the honest core of the milestone.

**Learned from data already in this repository**

| Component | Source | Tag |
| --- | --- | --- |
| `P(entry)` | The wordfreq join of §2, normalised into a distribution over the dictionary. `10^(zipf-9)`, renormalised. | **[measured]** for the 13.8% with an observed frequency |
| `P_ngram` | An order-4 character model over the dictionary's 297,747 Romanized spellings, Witten–Bell smoothed. | **[measured]** — every count comes from the data |
| Weight on entries with *no* observed frequency | Each tier's measured frequency coverage, add-one smoothed: `(ranked+1)/(size+1)`. | **[measured]** ratio, **[heuristic]** use of it |

**Not learned, because this repository holds no password corpus**

| Component | What is used instead | Tag |
| --- | --- | --- |
| `P(k)`, the segment count | Truncated geometric, `q = 0.5`, renormalised over 1–8 | **[assumption]** |
| `P(C)`, the category | Uniform over the five | **[assumption]** |
| `P(n)` for digit and symbol runs | Truncated geometric, `q = 0.5` / `0.35` | **[assumption]** |

These are the Weir-style *structure* probabilities, and learning them requires
passwords. There are none here. The synthetic benchmark corpus **must not** be
used for it: fitting the structure prior to the generator and then evaluating on
that generator's output would measure the generator. Geometric-and-uniform is
the maximum-entropy choice given a fixed mean and given nothing at all
respectively — the least that can be assumed while assuming anything.

**[measured]** §14.9 reports how far the conclusion moves when they change. It
is ±0.03 log10, which is the useful thing to know about an assumption.

### 14.3 The unranked bound

An entry with no observed frequency is given the **smallest observed**
probability, scaled by its tier weight. That bound is derived, not invented: a
word absent from a 26,653-word general frequency list is at most as common as
the rarest word on it. `frequency` stays `null` on the entry, exactly as in §3.2
— nothing is substituted for it.

### 14.4 Case

`P(surface | word)` keeps zxcvbn's *relative* weighting — `1/U` where `U` is the
variation count of §5.1 — and adds the **normaliser** `Z(L) = Σ 1/U` over all
`2^L` casings, which is what turns a cost multiplier into a probability.

The weighting is inherited on purpose and for the reason Milestone 2 gave:
holding the case model identical across estimators means a difference between
them is attributable to the lexicon, not to capital letters. Abandoning it here
would break the comparison this milestone extends. **[heuristic]**

`Bharat` costs exactly `log10 2` more than `bharat`, pinned by
`tests/test_pcfg_grammar.py`.

### 14.5 From probability to guess number

`P(password)` is **not** a guess number. The guess number is

```
G(x) = |{ y : P(y) >= P(x) }|
```

`1/P` is a well-known upper bound on it and over-states it badly near the head,
where many passwords share similar probabilities. Computing `G` exactly means
enumerating the grammar, which is the thing guessing is expensive for.

IndicPass uses the **Monte-Carlo strength estimator** of Dell'Amico & Filippone
(CCS 2015): draw `N` derivations from the model and

```
Ĝ(x) = (1/N) · Σ over { i : P(y_i) >= P(x) } of 1 / P(y_i)
```

which is **unbiased** — under `y ~ P`, the expectation of
`1{P(y) ≥ P(x)} / P(y)` is exactly the count above. Pinned by a test on a
grammar with a closed-form answer: restricted to single digits it generates ten
equiprobable passwords, and the estimator recovers `G = 10` without being told.

Two safeguards. `G ≤ 1/P` is applied unconditionally — at most `1/p` passwords
can have probability `≥ p` — which also makes the log-linear tail extrapolation
safe. And the curve is accumulated in log space, because `1/p` in the tail is
`10^90`.

**Nothing sampled is ever assembled into a password.** The estimator needs the
sampled *probabilities* and nothing else, so the sampler returns numbers and
discards the pieces it drew. A file of sampled passwords would be a cracking
wordlist; there is no point in this pipeline at which one exists.

`N = 200,000`, seed 42. **[measured]** Re-sampling from a different seed moves
every category by ±0.00 log10 (§14.9), so the estimator's own variance is
negligible next to every effect discussed.

### 14.6 The brute-force floor is not part of the grammar

The reported estimate is `min(Ĝ, 10^len)`. That floor is §6's assumption,
retained deliberately and kept **outside** the probability model: it is a
statement about an alternative attack, not a production of the grammar. An
attacker picks the cheaper of "use the model" and "enumerate strings".

Both numbers are reported separately — `grammar_log10_guesses` and
`bruteforce_log10_guesses` — and `floor_applied` says which won, so no reader
has to guess which produced a result. Turning it off is an ablation arm, not a
configuration: **[measured]** without it the random controls diverge without
bound (§14.9).

### 14.7 What the character model learned

**[measured]** `results/reports/pcfg_benchmark_hin.md`. Cost in `-log10 P` per
character; lower means the model finds the text likelier.

| Population | Cost per character |
| --- | ---: |
| Bank words the dictionary **contains** (trained on) | 0.935 |
| Bank words the dictionary is **missing** (never seen) | 0.936 |
| English control words | 1.047 |
| Random lower-case strings | 2.204 |
| **The brute-force floor** | **1.000** |
| *(a uniform 26-letter alphabet, for scale)* | *1.415* |

Two readings, and the second is the one that explains the whole benchmark.

1. **The model generalised.** Unseen Hindi costs 0.936 against 0.935 for Hindi
   it trained on — the same number. It learned the *shape* of Romanized Hindi,
   not a list of spellings, which is exactly the capability §12's coverage
   ceiling called for. Random strings cost 2.204, well above even a uniform
   alphabet, so the discrimination is real and large: **1.27 log10 per
   character** between Hindi and noise.

2. **The margin over the floor is not.** Only the gap between the model and the
   floor can ever reach a reported estimate, and that gap is **+0.064 log10 per
   character** — about 0.45 log10 on a seven-letter word, less than the
   structure and category priors charge for using the category at all. This is
   why the `no_character_model` ablation moves nothing, and it is a fact about
   the flat-10 floor Milestone 2 adopted, not about the character model.

### 14.8 Comparison methodology

Identical to §10: the same 1,400 generated samples, the same seed 42, the same
seven categories. Three estimators score every password in the same call, so
nothing is compared across runs. `scripts/pcfg_benchmark.py`.

The headline statistic is again **information added** — `min(PCFG, zxcvbn)`
minus zxcvbn alone — for the reason given in §10.2: IndicPass has no
common-password wordlist and "does the PCFG beat zxcvbn" is the wrong question.

### 14.9 Results, including the ones that go the wrong way

**[measured]** `results/reports/pcfg_benchmark_hin.md`.

**The random control is clean.** 0.0% of random strings in any cell were priced
below enumerating them, and only 4% had a dictionary segment in the winning
derivation at all. The PCFG does not invent lexical structure. Every other
number below is readable because of this one.

**The lexicon carries a real Indic signal.** Removing the `word` category costs
+0.36 log10 on `indic_word`, +0.52 on `indic_year`, and **+0.00 on random** —
the same signature §11 found, and the one a lexicon that was merely finding
noise could not produce.

**The PCFG estimates *more* guesses than zxcvbn everywhere**, by +0.58
(`indic_word`) to +4.07 (`english`). Two causes, both structural rather than
accidental: it has no English wordlist at all, and — unlike zxcvbn and unlike
§5 — its guess number counts passwords of *every* structure that outrank the
target, not just those sharing the assumed structure. Paying for the structure
choice is the more complete attacker model, and it makes the numbers larger.

**And so it adds less than the Milestone 2 estimator did.** Information added
against zxcvbn:

| Category | Milestone 2 | **PCFG** | min of all three |
| --- | ---: | ---: | ---: |
| indic_word | −0.37 | **−0.13** | −0.37 |
| indic_symbol | −0.48 | **−0.03** | −0.48 |
| indic_year | −0.33 | **−0.10** | −0.33 |
| indic_numeric | −0.25 | **−0.01** | −0.26 |
| mixed | −0.27 | **−0.02** | −0.27 |
| english | +0.00 | **+0.00** | +0.00 |
| random | −0.00 | **−0.00** | −0.00 |

Adding the PCFG to `min(Milestone 2, zxcvbn)` improves 2 more samples out of
1,400. **This contradicts the hypothesis that a probabilistic grammar would
extract more from the same lexicon than the Milestone 2 estimator does, and it
is reported rather than tuned around.** The mechanism is measured, not guessed:
the floor produces the reported number for 69–92% of samples in most categories
(§14.7 explains why), so the grammar is only reaching the answer on the
categories where it is not floored — `indic_year`, at a 20% floor rate, is where
it does most of its work.

**Sensitivity of every unmeasured choice.** Mean log10 relative to shipped:

| Arm | english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `no_bruteforce_floor` | +1.46 | +0.67 | +2.08 | +0.07 | +2.50 | +3.05 | **+∞** |
| `no_dictionary` | +0.29 | +0.36 | +0.07 | +0.52 | +0.07 | +0.13 | **+0.00** |
| `category_lexical` | −0.06 | −0.09 | −0.01 | +0.25 | +0.00 | −0.04 | +0.00 |
| `no_character_model` | −0.02 | +0.01 | −0.01 | +0.14 | −0.02 | +0.00 | +0.00 |
| `ngram_order_5` | −0.04 | −0.05 | +0.00 | −0.12 | +0.00 | −0.03 | +0.00 |
| `ngram_order_3` | −0.00 | +0.01 | −0.00 | +0.09 | −0.00 | +0.01 | +0.00 |
| `unranked_excluded` | +0.04 | +0.05 | −0.00 | +0.01 | +0.01 | +0.04 | +0.00 |
| `segments_0.7` | +0.02 | +0.03 | +0.00 | +0.01 | −0.00 | +0.01 | +0.00 |
| `segments_0.3` | −0.02 | −0.03 | −0.00 | +0.03 | +0.01 | −0.00 | +0.00 |
| `unranked_uniform` | −0.01 | +0.00 | +0.01 | +0.03 | +0.00 | −0.01 | +0.00 |
| `ngram_curated_only` | −0.00 | −0.01 | −0.00 | −0.03 | −0.00 | −0.01 | +0.00 |
| `curve_seed_7` | +0.00 | +0.00 | +0.00 | +0.00 | −0.00 | −0.00 | +0.00 |

The three things worth reading out of that table:

* **The unlearnable priors are not load-bearing.** Halving or raising the
  segment prior moves nothing by more than 0.03; a strongly lexical category
  prior moves nothing by more than 0.25. The part of this model that cannot be
  learned from anything in this repository is also the part that barely matters,
  which is the best outcome available given no password corpus.
* **The Monte-Carlo estimator is stable.** Re-seeding the curve moves every
  category by ±0.00. No result here is sampling noise.
* **The retained non-PCFG floor dominates.** It is the largest effect in the
  table by an order of magnitude, and on the random controls it is the entire
  answer.

### 14.10 Additional limitations of the PCFG

These are on top of §12, all of which still apply.

**11. The structure prior is not learned.** It cannot be, from this repository.
Measured to be non-load-bearing (±0.03), which is a different and weaker claim
than being right.

**12. The floor produces most of the reported numbers.** For 69–92% of samples
in most categories the grammar's own estimate is above `10^len`, so the answer
comes from a Milestone 2 assumption rather than from the model. A PCFG whose
output is usually overridden is not yet doing the work it was built for.

**13. The character model's contribution is invisible at this floor.** It
discriminates Hindi from noise by 1.31 log10 per character and beats the floor
by 0.064. Both are measured; only the second can reach an estimate.

**14. The guess number is not comparable term-for-term with zxcvbn's.** The
PCFG counts passwords of every structure that outrank the target; zxcvbn counts
within the structure it assumed. The PCFG's is the more complete model and the
larger number, and neither is validated.

**15. Terminal ambiguity is resolved by Viterbi, not by summing.** `P(password)`
under an ambiguous grammar is properly the sum over derivations; the parser uses
the maximum. That is the standard choice for guessing — an attacker pays for the
cheapest route — but it under-states the true probability of ambiguous
passwords.

**16. Still no reference attack.** Superseded by §15, which supplies a bounded
synthetic one. It is not a real cracking run and the accuracy claims it does
*not* license are enumerated in §15.10.

---

## 15. Reference-attack validation (Milestone 4)

Every comparison in §§1–14 is between models. Milestone 2 asked whether the
Indic lexicon lowers an estimate; Milestone 3 asked whether a grammar carries
information zxcvbn lacks. Neither could ask the only question that matters —
**which estimator is right** — because there was no quantity in the project that
was not itself an estimate.

This section supplies one:

> **observed reference rank** — the position at which a specific, fully
> specified attacker emits a specific password.

It is exact, reproducible from a seed and a config, and computed without
consulting any estimator. It is *not* a fact about real attackers, and §15.10
is unusually long because that distinction is where every over-claim would come
from.

### 15.1 What a reference attack has to be

Four requirements, and they conflict:

1. **Independent.** If candidates were ordered by an estimator's output, the
   validation would measure that estimator against itself.
2. **Exactly observable.** A rank that has to be extrapolated is another model.
3. **Bounded and reproducible.** No network, no leaked corpus, one seed.
4. **Defensible as an attack.** An arbitrary ordering would be independent and
   exactly observable and would mean nothing.

The standard offline attack — a wordlist run through an ordered rule set, as in
hashcat and John the Ripper — satisfies all four, so that is what is
implemented, in `src/indicpass/password/reference_attack.py`.

### 15.2 The attack

**Lexicon.** All 297,747 IndicDict spellings, in a documented order (§15.3).

**Rule programme.** Every combination of

| dimension | values |
| --- | --- |
| stem | one lexicon entry; two concatenated (the combinator attack) |
| case | as-is, `Capitalised`, `UPPER` — applied to the first word |
| suffix | none; 1–5 digits; a year in 1940–2029; one of 14 symbols; a symbol then 1–3 digits |

giving 66 rules, of which **63 fit the budget** and 3 (`word+word+digits5/*`)
do not. Enumeration is block by block, and within a block stem-major:

```
word/lower              297,747   candidates 1 .. 297,747
word/capitalized        297,747              297,748 .. 595,494
word/upper              297,747              595,495 .. 893,241
word+digits1/lower    2,977,470              893,242 .. 3,870,711
...
```

**Universe: 7,115,868,421,625,340 candidates — 10^15.85.**

**Ordering of the rules** is by ascending block size, ties broken by an explicit
family precedence so the straight wordlist runs before its cased variants.
Smallest-first is an **assumption**, with a maximum-entropy argument: absent any
information about which rule built the target, treating the rules as equally
likely to contain it makes expected cracks-per-guess inversely proportional to
block size. It is the same move the PCFG's structure prior makes (§14.2) and for
the same reason — there is no password corpus here to learn a better order from.
`family_rules` in §15.8 is the alternative, measured rather than argued about.

**Budget.** `max_candidates = 10^16`: about two hours of one eight-GPU rig
against MD5, and about thirty million years against bcrypt at cost 10. The same
number is a formality for one hash and impossible for another, which is the only
honest way to state an attack budget. It is deliberately set high enough that
coverage measures the *lexicon* rather than the budget; `budget_1e12` shows what
a smaller one costs.

**Nothing is enumerated.** Every rule is a product with a known factorisation,
so a rank is recovered by *inverting* the rule — strip the suffix, look the stem
up, multiply out the indices — in time linear in the password's length. The
universe is counted, not built. **No cracking wordlist exists at any point**, the
same property the PCFG sampler was built to have (§14.5).

**Ambiguity.** A string several rules can produce is emitted at the first of
them. `alpha` is both a lexicon entry and `al`+`pha`, and its rank is the
earlier reading. This is checked against ground truth: a small attack is
enumerated in full and every computed rank is compared with the position the
candidate actually occupies in the list.

**Reproducibility.** Every run rebuilds the primary arm from scratch and reports
whether the lexicon fingerprint, the attack fingerprint, the block programme,
all 1,400 ranks and the aggregate metrics match — all five do. Separately, two
invocations of `scripts/reference_attack.py` in **different processes** produce
byte-identical reports once the timestamp is removed
(`sha256:4579e2fe4ef2baa0…` for both). The attack is pinned by
`ATTACK_VERSION` 1.0, the `reference_attack` config block, and
`sha256:7d01bfe5fd530263…` over the ordered lexicon and the placed rules.

### 15.3 Independence, and where it is only partial

**Mechanically**, independence is complete and enforced three ways:

* `reference_attack.py` imports **nothing but the standard library** — not the
  meter, the scoring model, the matcher, the baseline or the PCFG, and not even
  the dictionary. It reads no guess number.
* A test parses that module's imports, asserts the set is stdlib-only, and fails
  on any estimator module.
* A test ranks a corpus with all three estimators replaced by objects that raise
  on contact, and asserts the ranks are unchanged.
* `scripts/reference_attack.py` scores every password *before* any attack object
  exists and reuses those predictions unchanged across every arm.

**Evidentially, it is partial, and this is the single most important caveat in
the section.** IndicPass prices a word at its rank in a frequency-ordered
wordlist (§3.1); the PCFG's word distribution is built from the same wordfreq
table (§14.2). An attack whose lexicon is ordered by that table is close to the
closed form of the Milestone 2 estimator, and finding that Milestone 2 predicts
it well would be close to a tautology.

So the lexicon ordering is an experimental variable, not a constant:

| ordering | evidence | shares it with |
| --- | --- | --- |
| `frequency` | observed corpus frequency, then a seeded shuffle | IndicPass, PCFG |
| `shuffled` | none — every spelling in seeded-shuffle order | nothing |
| `length` | shortest first, then alphabetical | nothing |

**A conclusion is only safe where the arms agree.** §15.8 reports all three.

### 15.4 Coverage, and what it structurally excludes

An uncovered password is given **no rank** — never the universe size, never a
censored bound, never a substituted value.

| category | targets | covered | median log10 rank |
| --- | ---: | ---: | ---: |
| english | 200 | 60.5% | 8.52 |
| indic_word | 200 | 41.0% | 5.32 |
| indic_numeric | 200 | 46.0% | 9.39 |
| indic_year | 200 | 47.5% | 7.55 |
| indic_symbol | 200 | 49.0% | 10.06 |
| mixed | 200 | 19.5% | 14.56 |
| random | 200 | **0.5%** | 11.14 |
| **all** | 1400 | **37.7%** | 8.50 |

Two of the nine required families are not categories. Case variation is
sprinkled through every Indic category by the generator, and "unseen spelling"
is a property of the *attacker's lexicon*. Both are therefore strata over the
same 1,400 samples — which is also what leaves the benchmark untouched:

| stratum | targets | covered |
| --- | ---: | ---: |
| case_variation | 453 | 42.2% |
| unseen_spelling | 872 | **0.0%** |
| in_lexicon | 528 | 100.0% |

That 0.0% is not a result, it is a **structural limit**, and it is the largest
weakness of this whole experiment. A password whose stem is not in the wordlist
is one no rule can produce, so the covered set and the in-lexicon set are the
same 528 samples. **This attack cannot rank an unseen Romanized-Hindi spelling
at all** — which is precisely the population the PCFG's character model was
built for (§14.7). Milestone 3's central claim therefore remains unvalidated,
and a different reference attack would be needed to test it.

Coverage is lexicon-limited rather than budget-limited: only 38% of the
benchmark's Indic word bank is in IndicDict, a Milestone 2 result the coverage
report already measures and the benchmark module documents on purpose. So the
metrics below are conditional on a selection that **favours the Indic
estimators**: they are scored only on words their dictionary contains.

### 15.5 The metrics, and why all of them

`error = predicted log10 guesses − observed log10 rank`. **Positive means the
estimator called the password stronger than the attack found it** — the
dangerous direction for a meter, because it is the one that tells someone a
crackable password is fine.

The metrics disagree with each other and the disagreement is the result, so no
single figure of merit is computed. A rank correlation says whether an estimator
*orders* passwords the way the attack does, which is what a 0–4 meter needs. An
absolute error says whether it gets the *number* right, which is what a risk
calculation needs. An estimator can be excellent at one and useless at the
other.

### 15.6 Results

528 covered targets, `frequency` arm, seed 42.

| estimator | Spearman | Pearson | mean err | MAE | RMSE | ±1.0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **IndicPass (M2)** | **0.900** | **0.889** | −1.951 | 1.955 | 2.440 | 26.3% |
| **PCFG (M3)** | 0.806 | 0.788 | **−0.377** | **1.370** | **1.934** | **50.2%** |
| zxcvbn 4.5.0 | 0.592 | 0.584 | −2.417 | 2.828 | 3.558 | 14.0% |
| min(M2, zxcvbn) | 0.734 | 0.726 | −3.011 | 3.014 | 3.670 | 8.9% |
| min(PCFG, zxcvbn) | 0.638 | 0.632 | −2.529 | 2.748 | 3.513 | 15.7% |
| min(M2, PCFG, zxcvbn) | 0.734 | 0.726 | −3.011 | 3.014 | 3.670 | 8.9% |

**The two questions have different answers, and both are clean.**

* **Ordering: IndicPass wins.** ρ = 0.900 against the PCFG's 0.806 and zxcvbn's
  0.592.
* **Magnitude: the PCFG wins, on every absolute metric.** Bias −0.38 against
  −1.95, MAE 1.37 against 1.96, and twice as many estimates within an order of
  magnitude.

Per category, the sharpest number in the milestone:

| category | ρ M2 | ρ PCFG | ρ zxcvbn |
| --- | ---: | ---: | ---: |
| english | 0.868 | 0.723 | 0.677 |
| **indic_word** | **0.694** | 0.558 | **0.005** |
| indic_numeric | 0.844 | 0.560 | 0.109 |
| indic_year | 0.602 | 0.531 | 0.251 |
| indic_symbol | 0.849 | 0.669 | 0.509 |
| mixed | 0.874 | 0.799 | 0.596 |

**zxcvbn's rank correlation on bare Romanized Hindi words is 0.005.** It carries
essentially no information about the order in which an Indic wordlist attack
reaches them. That is the Milestone 1 hypothesis, measured against something
other than another model, for the first time in this project.

**Three results that go against the grain, reported as measured.**

*The `min()` columns do worse than their parts.* This is not a defect of `min`.
Guessing cost really is a minimum over an attacker's options, and `min` is the
right quantity for **security**. It is the wrong quantity for **predicting one
specific attacker**, because it models the best of several and this reference is
one of them. The gap is the size of that difference, not a fault, and §15.9
forbids reading it as one.

*zxcvbn's −4.23 mean error on English is about the attack, not about zxcvbn.*
The reference attacker holds a Hindi wordlist; it reaches English words late,
via whatever English spellings Aksharantar happens to contain. zxcvbn is
modelling a better English attacker than this one, and is right to.

*Everything under-predicts.* All three estimators say fewer guesses than the
attack needed. This attack is inefficient relative to what the estimators model
— it enumerates 10^15.85 candidates with a naive ordering — so a negative bias
is the expected direction and is the safe one.

### 15.7 Calibration

Ordinary least squares of observed rank on predicted guesses. Slope 1,
intercept 0 is perfect **against this attack**.

| estimator | slope | intercept | r² |
| --- | ---: | ---: | ---: |
| IndicPass (M2) | 1.200 | 0.642 | **0.791** |
| PCFG (M3) | **0.898** | 1.205 | 0.621 |
| zxcvbn 4.5.0 | 0.682 | 4.345 | 0.341 |

zxcvbn's slope of 0.68 is a **compressed scale**: it spreads these passwords
over two-thirds of the range the attack does. The PCFG's 0.90 is the closest to
one; IndicPass's 1.20 slightly exaggerates but explains much the most variance.

Bias by decile of prediction shows the difference in kind:

* **IndicPass** drifts monotonically from −0.82 in the cheapest decile to −3.19
  in the ninth. Its error is *structured*: the further up the scale, the more it
  under-predicts.
* **The PCFG** stays between −1.36 and +0.49 for ten deciles and then jumps to
  +2.74 in the last. Its error is *flat* until the top of the range.

The `points` array in the JSON carries thinned `(predicted, observed)` pairs for
plotting. A pair of numbers identifies no password.

### 15.8 Does the answer depend on the attacker?

Each arm is the attack with exactly one thing changed.

| arm | independent | coverage | ρ M2 / PCFG / zxcvbn | MAE M2 / PCFG / zxcvbn |
| --- | --- | ---: | --- | --- |
| `frequency` | **no** | 37.7% | 0.900 / 0.806 / 0.592 | 1.95 / 1.37 / 2.83 |
| `shuffled` | yes | 37.7% | 0.885 / 0.793 / 0.590 | 2.20 / 1.32 / 2.96 |
| `length` | yes | 37.7% | 0.890 / 0.809 / 0.605 | 2.16 / 1.26 / 2.90 |
| `family_rules` | no | 37.7% | 0.812 / 0.716 / 0.559 | 2.19 / 1.56 / 3.02 |
| `budget_1e12` | no | 32.9% | 0.866 / 0.783 / 0.558 | 1.66 / 1.09 / 2.37 |
| `no_combinator` | no | 30.5% | 0.918 / 0.875 / 0.714 | 1.47 / 0.92 / 2.07 |

**In all six arms, without exception, IndicPass wins the rank correlation and
the PCFG wins the mean absolute error.** The ordering result survives removing
the shared frequency evidence entirely (`shuffled`: 0.885 against 0.900), which
is what makes it a statement about the estimators rather than about wordfreq.
The rule ordering is the most load-bearing choice in the attack — `family_rules`
costs every estimator about 0.09 of correlation — and it changes no ranking.

### 15.9 How to read this

1. `observed reference rank` is a fact about **one** attacker.
   `estimated guess number` is a model output. They are never the same quantity
   and are never averaged together.
2. A positive signed error means the estimator called a password **stronger**
   than this attack found it.
3. A result that appears only in the `frequency` arm is a statement about shared
   evidence, not about estimator quality.
4. The `min()` columns are the right quantity for security and the wrong one for
   predicting a single attacker. Their larger error is not evidence against
   combining estimators.
5. Nothing here licenses a claim about real-world cracking accuracy.

### 15.10 Limitations

These are on top of §12 and §14.10.

**17. This is one attacker, not the space of them.** No leaked-password list, no
Markov or PCFG guess generator, no leet substitution, no keyboard walks, no
targeted personal data, no English wordlist beyond what IndicDict happens to
contain. An estimator that predicts *this* attack well may predict another
badly.

**18. The attack cannot rank an unseen spelling — 0 of 872.** §15.4. The
population Milestone 3's character model exists for is structurally outside the
measurement, so Milestone 3's central claim is still unvalidated.

**19. Coverage is 37.7%, and the covered set favours the Indic estimators.**
Metrics are conditional on the attack working, and the attack works exactly
where IndicDict has the word.

**20. The rule ordering is an assumption with a maximum-entropy argument, not a
measurement.** Measured to move every correlation by about 0.09 and no ranking
(§15.8), which is a weaker claim than being right.

**21. The `frequency` arm shares evidence with two of the three estimators.**
Mitigated by the `shuffled` and `length` arms, not eliminated.

**22. The corpus is still generated.** Everything §12.1 says about the benchmark
applies unchanged: these are plausible synthetic passwords, not observed ones.
A reference attack against a synthetic corpus validates the *estimators'
ordering*, not the corpus's realism.

### 15.11 The answer to the research question

> Is M2's within-structure guess model or the PCFG's probability-over-all-
> structures model closer to observed attacker ordering?

**M2 is closer to the ordering; the PCFG is closer to the magnitude.** Both hold
in all six arms including the two that share no evidence with either estimator.

That is not a contradiction, and it does not overturn Milestone 3. Milestone 3
measured *information added under a minimum* and found the PCFG added little;
this measures *agreement with an enumeration* and finds the PCFG much better
calibrated and IndicPass much better ordered. They are different questions and
the answers are consistent: the PCFG's Monte-Carlo count over all structures
gets the scale right, and IndicPass's wordlist-position arithmetic gets the
sequence right, because a wordlist-and-rules attack *is* a sequence of wordlist
positions.

**The shipped estimator does not change.** A 0–4 strength meter's job is to
order passwords, IndicPass orders them best, and §15.10 lists six reasons this
result cannot carry more weight than that.

---

## 16. Out-of-lexicon attack validation (Milestone 5)

§15.10 limitation 18 is the one that mattered:

> **The attack cannot rank an unseen spelling — 0 of 872.** The population
> Milestone 3's character model exists for is structurally outside the
> measurement, so Milestone 3's central claim is still unvalidated.

That is a property of the *attacker*, not of the estimators. Milestone 4's
universe is a wordlist crossed with rules, so a password built from a spelling
the wordlist lacks is not in it at all — and `namaste`, `sharma` and `ghar` are
exactly such spellings, because Aksharantar's Hindi split does not contain them
(§6). This section builds a second attacker whose universe **does** contain
them, and asks Milestone 3's question against it.

The implementation is `src/indicpass/password/character_attack.py`, the
partition is `src/indicpass/password/oov.py`, the intervals are
`src/indicpass/password/uncertainty.py`, and the pipeline is
`scripts/milestone5_oov_attack.py`.

### 16.1 The one structural change

Milestone 4's candidate is `case(word from lexicon) + suffix`. Milestone 5's is

```
candidate = case(stem) + suffix
```

where **`stem` is any string over the 26 ASCII lower-case letters** within a
length band, generated by a character model rather than looked up. That single
substitution is the whole design. It removes the wordlist, and with it the
structural exclusion: an out-of-lexicon spelling is now reachable on exactly the
same terms as one the dictionary holds, just at whatever cost the character
model assigns it. No combinator rule is needed either — `merapyaar` is a
nine-character stem.

### 16.2 Ordering a universe you cannot list

The universe is about 10^22 stems. It is ordered by an integer **level**:

```
level(candidate) = shape_level(case, family) + stem_level(stem)
stem_level(s)    = Σᵢ q(-log10 P(sᵢ | contextᵢ)) + q(-log10 P(END | context))
shape_level      = q(log10 3) + q(log10 F) + q(log10 |family|)
q(x)             = floor(x / precision + 0.5)
```

Quantisation is what makes this countable. Because levels are integers, the
number of candidates at each one is a dynamic programme over
`(remaining length, context, remaining level)`:

```
W[0][h][m] = 1 if m == level(h, END) else 0
W[k][h][m] = Σ_c W[k-1][h·c][m - level(h, c)]
```

so the universe is **counted, never built**, and a rank is recovered by
inverting the ordering — every candidate at a cheaper level, plus every
candidate at this level in an earlier shape, plus every stem of this shape that
sorts first (a digit-DP over the same table), plus the suffix index. That is
linear in the password's length and touches nothing that precedes it. It is the
level-based scheme published cracking tools use, for the same reason.

The total order, in full: ascending level; then shape index (shapes sorted by
`(shape level, family order, case order)`); then stem by length ascending and
then lexicographically; then suffix index within its family.

`tests/test_character_attack.py` enumerates a toy universe of 73,710 candidates
in full and asserts that **every** computed rank equals the position the
candidate actually occupies in that list — first, last, repeated characters,
maximum-length stems, and the one genuine collision (a one-letter stem is
emitted by both `capitalized` and `upper`, and must be reached at the earlier).

### 16.3 The budget, and the three assumptions

The budget is **inherited from Milestone 4**: 10^16 candidates. That is not a
tuned number, it is the same number, chosen so the two attacks cost the same and
the difference in their coverage is a statement about the candidate model rather
than about how long each attacker was allowed to run. It buys every candidate at
level ≤ 70, a universe of 6,158,855,235,274,035 = 10^15.79.

Three assumptions, all stated in the report and all with sensitivity arms:

1. **P(case) and P(suffix family) are uniform.** Maximum entropy, for the reason
   §14 gives for the structure prior: there is no password corpus here to learn
   one from.
2. **Costs are quantised and summed.** A sum of quantised costs is not the
   quantised sum. The level *defines* this attack's order; it is not claimed to
   be a probability. Arm: `precision_0.5`.
3. **Additive (Laplace) smoothing, α = 1, backing off to the longest observed
   context.** Deliberately *not* the PCFG's Witten–Bell (§14): a different
   estimator on the same counts, so the attack is not a re-implementation of the
   thing it scores. Arms: `smoothing_0.1`, `order_2`.

### 16.4 Independence, and where it is only partial

`character_attack.py` imports **nothing but the standard library** — not the
meter, scoring, matcher, baseline or PCFG, and not even the dictionary
(`dictionary_stem_corpus` duck-types an `IndicDict` and reads one attribute).
The tests enforce it four ways: by parsing the module's import set and
asserting it is stdlib-only, by denylisting the estimator modules, by ranking a
corpus with all three estimators replaced by objects that raise on contact, and
by parsing `main()` to assert the corpus is scored **before** any attack object
is constructed.

The evidential half is weaker and is the reason the `uniform` arm exists:

> **Under `model=indicdict` the character model is trained on the same romanized
> spellings the PCFG's own n-gram is trained on.** Different order, different
> smoothing, different code — the same data. That arm favours the PCFG by
> construction.

`uniform` removes it completely: every symbol costs the same, the ordering
collapses to length-then-lexicographic, and no estimator has any informational
advantage. **A conclusion is only safe where the two agree.** Every conclusion
below holds in both.

### 16.5 Coverage — the limitation, removed

| | Milestone 4 | Milestone 5 |
| --- | ---: | ---: |
| all 1,400 targets | 528 (37.7%) | **1,091 (77.9%)** |
| out-of-lexicon Indic | **0 of 872** | **468 of 468 (100%)** |

Every out-of-lexicon Indic target is now ranked. The 309 that remain unreachable
are unreachable for named, reported reasons — `no_shape` 157 (a capital or a
digit somewhere the universe does not admit one), `level_above_budget` 147,
`stem_too_long` 5 — and every one of them is given **no rank at all**. An
unreachable target is never assigned the universe size, a censored bound or any
substituted value; `unreachable != universe_size` is asserted in the tests and
printed in the report.

### 16.6 The control: does the model carry information?

Unlike Milestone 4, this attack *can* reach a random lower-case string — its
universe is every letter string within the bounds. So the control is not "does
it reach noise" but "how much later":

| population | median log10 attack rank |
| --- | ---: |
| in-lexicon | 9.18 |
| out-of-lexicon Indic | **8.14** |
| random controls | **14.62** |

**6.49 orders of magnitude** separate an out-of-lexicon Hindi spelling from
noise. A separation near zero would have meant the character model was matching
noise and would have invalidated every OOV rank in the report. It is not, and
this is the strongest single result of the milestone: *a character model trained
only on a transliteration dictionary really does put Hindi-shaped spellings it
has never seen millions of times earlier in an attack than random strings.* The
mechanism Milestone 3 proposed exists. Whether **M3's estimator** exploits it
better than M2 is a separate question, and the answer is below.

### 16.7 M3 against M2, on the 468 out-of-lexicon Indic targets

Percentile bootstrap, 2,000 resamples, seed 42, paired — the same resample
scores both estimators, so the interval is on their *difference*.

| | IndicPass (M2) | PCFG (M3) | zxcvbn | M3 − M2 [95% CI] |
| --- | ---: | ---: | ---: | --- |
| Spearman ρ | **0.919** [0.900, 0.934] | 0.858 [0.827, 0.885] | 0.772 | **−0.060** [−0.078, −0.044] |
| Pearson r | **0.917** | 0.878 | 0.744 | |
| MAE | 1.128 [1.052, 1.204] | **1.037** [0.971, 1.105] | 2.003 | **−0.091** [−0.141, −0.042] |
| RMSE | 1.397 | **1.274** | 2.464 | |
| ±1.0 log10 | 0.498 | **0.528** | 0.244 | |
| calibration slope | **1.005** [0.961, 1.051] | 0.882 [0.840, 0.923] | 0.914 | |
| r² | **0.841** | 0.771 | 0.554 | |

Both intervals exclude zero, in opposite directions. The direction is identical
in **all seven arms**, including `uniform`:

| arm | shares evidence | ρ M2 | ρ M3 | M3 wins ρ | M3 wins MAE |
| --- | --- | ---: | ---: | --- | --- |
| `indicdict` | yes | 0.919 | 0.858 | no | yes |
| `uniform` | **no** | 0.952 | 0.902 | no | yes |
| `holdout_half` | yes | 0.922 | 0.862 | no | yes |
| `order_2` | yes | 0.923 | 0.862 | no | yes |
| `smoothing_0.1` | yes | 0.918 | 0.858 | no | yes |
| `precision_0.5` | yes | 0.929 | 0.874 | no | yes |
| `budget_1e12` | yes | 0.908 | 0.840 | no | yes |

### 16.8 The answer to the research question

> Does the PCFG's character model provide useful attack-order information for
> Romanized Indic passwords whose spelling is absent from IndicDict?

**Partially supported, by a rule fixed before the numbers were seen.**

* **Ordering — unsupported.** M3's rank correlation is *below* M2's by 0.060
  [−0.078, −0.044], in every arm.
* **Calibration — supported.** M3's absolute error is below M2's by 0.091
  [−0.141, −0.042], in every arm, and its mean signed error is roughly half M2's.

This is the **same split Milestone 4 found on the in-lexicon population**
(§15.11), now shown to hold on the population Milestone 4 could not reach:
*M2 is closer to the ordering, M3 is closer to the magnitude*. That the pattern
survives onto a disjoint population, under an attacker with no wordlist, is a
stronger statement than either milestone made alone.

It also sharpens what Milestone 3's character model is *for*. On out-of-lexicon
targets both Indic estimators fall back on something strongly length-driven, and
so does the attack; M2's brute-force floor tracks that ordering slightly better,
while M3's character term is what pulls the *magnitude* onto the attack's scale
(calibration slope 0.88 against M2's 1.01 is M3 over-correcting, not M3 failing).
Both beat zxcvbn on every metric by a wide margin, which is the one comparison
that is not close.

**The shipped estimator does not change**, for the reason §15.11 gives: a 0–4
meter's job is to order passwords, and M2 orders them best here too.

### 16.9 Reproducibility

The experiment is run **twice, in two separate processes**, and the two reports
are compared byte for byte after removing `generated_at` and the reproducibility
block itself. They are identical:

```
canonical SHA-256   d1e94bfefe9449390eeb7f062bae6f976a7c86b5890730f3d1b83b41bfd7b2b7
attack fingerprint  0166a4f715559362431d01a4088df7e42ba83147f181dcb7ab0db84789c8a435
model fingerprint   ab07531bd53c40870fbdea88e737fd63d9bf19b9468344cb433c827e7343224f
corpus digest       2356a7d602926706fc7ed0d67884d7c1c9f8e4e57b456d00dc3bdbcb1a8edd6a
dictionary file     2a91a9f3c8fb699277fab68905bb94476d410c765fae15461e4d38f655aa6642
pcfg artefact       189b32a765f313f230da5e73cba47135974420985157155951f40fa858dc0827
```

A second process rather than a second call in one interpreter, because a shared
cache inside one interpreter could hide a dependence on run order. Reproduce
with:

```bash
python scripts/milestone5_oov_attack.py --languages hin --samples 200 --seed 42 \
    --resamples 2000
```

### 16.10 Limitations

These are on top of §12, §14.10 and §15.10.

**23. The universe admits digits and symbols only as a bounded tail, and a
capital only as the first letter.** `meraNamaste` and `me9ra` are outside it and
are reported unreachable, not approximated. That is why 157 targets fail with
`no_shape`, and it is a real restriction on what this attacker models.

**24. Coverage is 77.9%, and the metrics are conditional on it.** Better than
Milestone 4's 37.7% and still a selection. The out-of-lexicon Indic stratum is
the exception and the one that matters: it is 100%.

**25. The `indicdict` arm shares training evidence with the PCFG's n-gram.**
Mitigated by `uniform`, not eliminated. Every conclusion above is stated only
because it holds in both.

**26. The character model is trained on a *type* distribution.** Each spelling
counted once, so it models what a Romanized Hindi word looks like, not how often
one is written. An attacker with a password corpus would order candidates better
than this one does.

**27. The OOV partition rules are a classification heuristic.** They will
mislabel some targets in both directions. Nothing in the headline finding rests
on them: the in-lexicon/out-of-lexicon split is exact dictionary membership, and
the partitions only keep the OOV population from being reported as one lump.

**28. Quantised levels are not probabilities.** The level defines this attack's
order. A rank is where *this* attacker arrives at a password, not an estimate of
what a real one would need.

**29. The corpus is still generated.** Everything §12.1 and §15.10 (22) say
applies unchanged.

---

## 17. The final integration decision, and the freeze

Milestones 1–5 are complete and the research implementation is **frozen at
`v1.0-research`**. This section records the one product decision the results
force, and what "frozen" means.

### 17.1 What the 0–4 score is computed from

`IndicPassMeter.score()` returns a `PasswordStrengthResult` whose
`strength_score` is a threshold on **M2's `log10_guesses` and nothing else**.
M3 and zxcvbn are attached to the same result object as `.pcfg` and `.baseline`,
reported alongside and never substituted in.

That was the arrangement before any attack existed, and the measurements did not
change it. They did turn it from a default into a decision:

* **A 0–4 band is an ordering device.** It answers "is this password weaker than
  that one", which is a question about rank, not about magnitude. Both attackers
  agree M2 has the higher rank correlation — on all targets, on in-lexicon
  targets, and on the out-of-lexicon targets M3 was built for (§16.7).
* **The band discards exactly what M3 is better at.** M3's advantage is absolute
  error and calibration slope. Mapping a guess number onto five buckets throws
  the magnitude away, so an estimator that is 0.09 orders of magnitude closer
  and 0.06 worse at ordering is strictly worse *for this output*.
* **A caller who needs the magnitude can read it.** `result.pcfg` carries M3's
  estimate verbatim. Nothing hides the trade-off; the API exposes both numbers
  because they answer different questions.

### 17.2 Why there is no fusion estimator

The obvious next move — combine M2's ordering with M3's calibration — is
deliberately **not** taken, and the reason is methodological rather than
technical.

Any fusion has parameters. Fitting them requires data. The only labelled data in
this project is the 1,400-sample benchmark, which is also the evaluation set.
Fitting a combiner on it and then reporting its performance on it would measure
the generator, and the resulting number would be indistinguishable from a real
improvement while being worth nothing. There is no held-out password corpus to
fit on instead, because there is no password corpus at all.

So the honest options were: ship an unfitted combination, or ship neither. An
unfitted `min(M2, M3)` was measured — it is one of the `min()` columns in every
report — and it scores **worse than either part** against both attackers, which
is correct and not a bug: `min` is the right quantity for a security bound and
the wrong one for predicting one specific attacker's ordering.

A fusion estimator is listed in future work with the condition attached: only
with a fitting corpus disjoint from the evaluation benchmark.

### 17.3 What "frozen" means

* **M2, M3, M4 and M5 are not modified in response to any result.** They were
  not during the milestones and are not now. Every number in
  `results/reports/final_report.md` was produced by the code as committed.
* **The estimator semantics, the attack definitions, the benchmark generator and
  the config defaults are fixed.** Each carries a version constant
  (`GENERATOR_VERSION`, `ATTACK_VERSION`) and a fingerprint, so a future change
  cannot silently produce numbers that get compared against these.
* **Reproducibility is verified rather than asserted.**
  `scripts/verify_reproducibility.py` runs all eight pipelines twice in separate
  processes and compares the canonical payloads byte for byte. The expected
  digests are in `docs/REPRODUCING.md` §5.
* **Future work is additive.** Leet mangling, more languages, a fitted fusion
  estimator, a real cracking run — each is a new milestone with its own version
  constant, not an edit to these.

### 17.4 The one claim this project makes

> For Romanized Indic passwords, an Indic-aware estimator predicts a bounded
> reference attacker's ordering substantially better than a generic one does,
> and the two Indic estimators trade off against each other: the lexical model
> orders better, the probabilistic model calibrates better.

Everything else in this document is either evidence for that, a bound on it, or
a statement of what it does not license.

---

## What this is not

`log10_guesses` is the logarithm of a search cost under one specific attacker
model. It is **not entropy**. Entropy is a property of a probability
distribution over passwords, and no such distribution is estimated anywhere in
this engine — there is no `P(password)`, no normalisation, nothing to take an
expectation over. The word is not used, and a guess number must not be
converted to "bits" and presented as if it were.

The distinction is not pedantry. Entropy would license statements about a
population of passwords; a guess number licenses only a statement about one
password against one modelled attacker. Only the second is supported here.
