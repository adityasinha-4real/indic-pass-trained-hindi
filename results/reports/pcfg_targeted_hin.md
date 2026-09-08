# PCFG targeted cases and random control

- **Generated:** 2026-09-07T14:02:37+00:00
- **Git commit:** `8a09173ef35109e4d0310c7a8b118a9afb021f5b`
- **Baseline:** zxcvbn 4.5.0
- **Dictionary:** 297,747 entries, 40,966 with an observed frequency (13.8%)
- **Frequency source:** `wordfreq-3.1.1/hi/small`
- **Grammar:** order-4 character model, geometric(q=0.5) segment prior truncated at 8, uniform category prior
- **Guess curve:** 200,000 sampled derivations, seed 42, 1328 stored points
- **Dictionary fingerprint:** `sha256:9e17fb7da40a0622...`
- **Corpus:** 1,400 generated samples, seed 42, generator 1.0

Rows are keyed on `sample_id`. **No row maps an id to a password**, and no
composed password -- word plus digits, symbol, year, or any random string --
is written anywhere. The corpus regenerates exactly from the seed above.

> **The PCFG is a model, not a measurement of attacker behaviour.** Nothing
> here has been validated against an observed cracking run. "Estimates fewer
> guesses" is a statement about two models, not about reality.

## The question

> What does the grammar actually derive, one case at a time, and does it invent lexical structure in random strings?

Rows are keyed on case_id. The probe passwords are committed source in src/indicpass/password/pcfg/probe.py, where the whole instrument can be read at once; what is forbidden -- and what this report does not do -- is publish a table pairing an identifier with a password.

## Cases

`G` is the reported PCFG estimate, `grammar` what the model said before the
brute-force floor, `bf` what enumerating the string would cost. When
`grammar > bf` the floor won and the grammar contributed nothing.

| Case | Family | Len | Derivation | log10 P | grammar | bf | **PCFG G** | M2 | zxcvbn | min(PCFG,zx) |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `single-01` | single_indic_word | 6 | `word` | -4.46 | 2.73 | 6.0 | **2.73** | 1.62 | 4.06 | 2.73 |
| `single-02` | single_indic_word | 7 | `word` | -6.34 | 4.93 | 7.0 | **4.93** | 3.48 | 3.24 | 3.24 |
| `single-03` | single_indic_word | 7 | `unknown` | -9.89 | 8.20 | 7.0 | **7.00** | 7.00 | 3.59 | 3.59 |
| `single-04` | single_indic_word | 6 | `unknown` | -7.54 | 5.97 | 6.0 | **5.97** | 4.72 | 3.74 | 3.74 |
| `year-01` | indic_word_year | 10 | `word+year` | -7.59 | 6.02 | 10.0 | **6.02** | 4.33 | 8.14 | 6.02 |
| `year-02` | indic_word_year | 11 | `word+year` | -9.47 | 7.82 | 11.0 | **7.82** | 5.92 | 5.26 | 5.26 |
| `year-03` | indic_word_year | 11 | `unknown+year` | -13.03 | 11.17 | 11.0 | **11.00** | 9.43 | 6.19 | 6.19 |
| `digits-01` | indic_word_digits | 9 | `word+digits` | -9.36 | 7.72 | 9.0 | **7.72** | 4.96 | 6.06 | 6.06 |
| `digits-02` | indic_word_digits | 10 | `word+digits` | -11.24 | 9.45 | 10.0 | **9.45** | 6.78 | 6.50 | 6.50 |
| `digits-03` | indic_word_digits | 11 | `word+digits` | -11.96 | 10.14 | 11.0 | **10.14** | 6.91 | 9.06 | 9.06 |
| `multi-01` | multiple_indic_words | 10 | `word+word` | -9.40 | 7.75 | 10.0 | **7.75** | 4.44 | 8.14 | 7.75 |
| `multi-02` | multiple_indic_words | 10 | `word` | -7.88 | 6.30 | 10.0 | **6.30** | 4.56 | 7.37 | 6.30 |
| `multi-03` | multiple_indic_words | 15 | `word+word+word` | -14.51 | 12.56 | 15.0 | **12.56** | 8.06 | 12.66 | 12.56 |
| `mixed-01` | indic_and_english | 14 | `word+word` | -11.40 | 9.62 | 14.0 | **9.62** | 5.88 | 6.06 | 6.06 |
| `mixed-02` | indic_and_english | 13 | `unknown+word` | -16.95 | 14.91 | 13.0 | **13.00** | 8.91 | 6.41 | 6.41 |
| `mixed-03` | indic_and_english | 13 | `word+word` | -13.37 | 11.49 | 13.0 | **11.49** | 7.88 | 5.26 | 5.26 |
| `symbol-01` | indic_and_symbols | 11 | `word+symbols+year` | -10.30 | 8.57 | 11.0 | **8.57** | 6.91 | 8.48 | 8.48 |
| `symbol-02` | indic_and_symbols | 8 | `word+symbols` | -9.05 | 7.43 | 8.0 | **7.43** | 4.85 | 4.68 | 4.68 |
| `symbol-03` | indic_and_symbols | 13 | `word+symbols+word` | -16.05 | 14.05 | 13.0 | **13.00** | 8.18 | 10.73 | 10.73 |
| `case-01` | case_variation | 6 | `word` | -4.76 | 3.30 | 6.0 | **3.30** | 1.92 | 4.36 | 3.30 |
| `case-02` | case_variation | 6 | `word` | -4.76 | 3.30 | 6.0 | **3.30** | 1.92 | 4.36 | 3.30 |
| `case-03` | case_variation | 6 | `word` | -6.07 | 4.55 | 6.0 | **4.55** | 3.23 | 5.67 | 4.55 |
| `case-04` | case_variation | 10 | `word+year` | -7.89 | 6.31 | 10.0 | **6.31** | 4.51 | 8.24 | 6.31 |
| `unseen-01` | unseen_token | 8 | `unknown` | -9.00 | 7.39 | 8.0 | **7.39** | 8.00 | 8.00 | 7.39 |
| `unseen-02` | unseen_token | 10 | `unknown` | -12.25 | 10.42 | 10.0 | **10.00** | 8.64 | 10.00 | 10.00 |
| `unseen-03` | unseen_token | 8 | `unknown+unknown` | -26.83 | 24.35 | 8.0 | **8.00** | 8.00 | 8.00 | 8.00 |
| `unseen-04` | unseen_token | 10 | `unknown+digits` | -14.80 | 12.84 | 10.0 | **10.00** | 10.00 | 5.60 | 5.60 |
| `random-01` | random_string | 10 | `unknown+unknown` | -39.32 | 36.25 | 10.0 | **10.00** | 10.00 | 9.98 | 9.98 |
| `random-02` | random_string | 10 | `digits+unknown+digits+unknown+digits+unknown` | -38.61 | 35.57 | 10.0 | **10.00** | 10.00 | 10.00 | 10.00 |
| `random-03` | random_string | 12 | `*unsupported*` | -inf | inf | 12.0 | **12.00** | 12.00 | 12.00 | 12.00 |

## What each case tests

| Case | Note |
| --- | --- |
| `single-01` | A common Hindi word, present in the dictionary with a measured rank. |
| `single-02` | A named entity, present, priced by measured rank. |
| `single-03` | Absent from the corpus. Only the character model can explain it. |
| `single-04` | A very common surname, absent from the corpus. The coverage ceiling. |
| `year-01` | The canonical structure: a dictionary word and a recent year. |
| `year-02` | A named entity and a birth year. |
| `year-03` | The same structure with the word absent from the dictionary. |
| `digits-01` | A digit run that is not a year, so the year terminal must not fire. |
| `digits-02` | A culturally common three-digit suffix. The grammar has no special case for it. |
| `digits-03` | A five-digit run: the length prior's cost should dominate the word's. |
| `multi-01` | Two of the commonest words in Hindi, concatenated. |
| `multi-02` | A set phrase, as two dictionary lookups. |
| `multi-03` | Three segments: the structure prior charges for the extra split. |
| `mixed-01` | An Indic word and the commonest English password word. |
| `mixed-02` | The same pair in the other order. |
| `mixed-03` | A named entity and an English wordlist staple. |
| `symbol-01` | Word, symbol, year: three segments, the shape a password policy produces. |
| `symbol-02` | A single trailing symbol, the cheapest possible symbol run. |
| `symbol-03` | A three-character symbol run between two words. |
| `case-01` | Capitalised. Must cost about twice the lower-case form, not orders more. |
| `case-02` | All upper case: the same two variations as capitalised. |
| `case-03` | Genuinely mixed case, where the variation count really does grow. |
| `case-04` | Case variation inside a multi-segment structure. |
| `unseen-01` | Hindi-shaped and absent: the case the character model exists for. |
| `unseen-02` | Two Hindi-shaped pieces, at least one unseen. |
| `unseen-03` | Roman letters with no Hindi shape at all. Must NOT look like a word. |
| `unseen-04` | An unseen word with digits -- the Milestone 1 fragment pathology's home. |
| `random-01` | Ten lower-case letters, no structure. The control the model must not flatter. |
| `random-02` | Mixed alphanumeric, ten characters. |
| `random-03` | Full charset, twelve characters. |

## Random control, full sweep

word_rate is how often the winning derivation contains a dictionary segment; below_bruteforce_rate is how often the grammar alone priced a random string below enumerating it. The second is the one that could change an estimate. A model that read random strings as cheaper than brute force would be inventing structure, and every Indic result would have to be read as the same artefact.

300 strings per cell, seed 42.

| Alphabet | Length | word in derivation | grammar < brute force | mean(grammar - bf) | mean vs zxcvbn |
| --- | ---: | ---: | ---: | ---: | ---: |
| lower | 6 | 2% | **0.0%** | +7.85 | +0.05 |
| lower | 8 | 1% | **0.0%** | +10.33 | +0.04 |
| lower | 10 | 3% | **0.0%** | +13.09 | +0.07 |
| lower | 12 | 2% | **0.0%** | +15.79 | +0.09 |
| lower | 14 | 4% | **0.0%** | +18.34 | +0.12 |
| alnum | 6 | 0% | **0.0%** | +10.54 | +0.02 |
| alnum | 8 | 1% | **0.0%** | +14.38 | +0.02 |
| alnum | 10 | 3% | **0.0%** | +17.34 | +0.03 |
| alnum | 12 | 1% | **0.0%** | +inf | +0.04 |
| alnum | 14 | 2% | **0.0%** | +inf | +0.03 |
| full | 6 | 0% | **0.0%** | +12.89 | +0.02 |
| full | 8 | 2% | **0.0%** | +16.60 | +0.01 |
| full | 10 | 0% | **0.0%** | +inf | +0.01 |
| full | 12 | 1% | **0.0%** | +inf | +0.03 |
| full | 14 | 2% | **0.0%** | +inf | +0.02 |

