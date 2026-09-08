# IndicDict coverage -- hin

- **Generated:** 2026-09-08T04:35:22+00:00
- **Git commit:** `8a09173ef35109e4d0310c7a8b118a9afb021f5b`
- **Dictionary:** `data/dictionaries/indicdict_hin.jsonl` (297,747 entries, built 2026-09-07T10:51:55+00:00)
- **Frequency source:** `wordfreq-3.1.1/hi/small` -- Zipf frequency: log10(occurrences per billion tokens) of the NATIVE-SCRIPT word in a general text corpus. A corpus word frequency -- not a password frequency and not a model score.
- **Probe set:** 163 words from `indicpass.password.benchmark.INDIC_WORDS` (generator 1.0)

Written from usage, not sampled from IndicDict. No word is ever added to the dictionary because it appears here.

## Headline

| Probe | Words | Present | Absent | Coverage | Priced by rank | By tier fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Core (brief) | 15 | 8 | 7 | 53.3% | 8 | 0 |
| Full bank | 163 | 62 | 101 | 38.0% | 58 | 4 |
| English controls | 10 | 7 | 3 | 70.0% | 3 | 4 |

## Dictionary-wide pricing

40,966 of 297,747 entries (13.8%) have an observed corpus frequency and are priced by measured rank. The rest fall back to their provenance tier.

| Tier | Entries | Ranked | Unranked | Fallback offset |
| --- | ---: | ---: | ---: | ---: |
| human_romanized | 30,400 | 13,437 | 16,963 | 40,966 |
| curated_entities | 25,005 | 1,747 | 23,258 | 57,929 |
| curated_other | 122,342 | 23,612 | 98,730 | 81,187 |
| mined | 120,000 | 2,170 | 117,830 | 179,917 |

## Core probe, word by word

| Word | Present | Native form | Tier | Source | Frequency | Rank | Priced by |
| --- | :---: | --- | --- | --- | ---: | ---: | --- |
| `namaste` | no | -- | -- | -- | -- | -- | -- |
| `namaskar` | no | -- | -- | -- | -- | -- | -- |
| `dhanyavaad` | no | -- | -- | -- | -- | -- | -- |
| `dhanyavad` | yes | धन्यवाद | curated_other | AK-Freq | 5.19 | 861 | observed_rank |
| `bharat` | yes | भारत | curated_entities | Wikidata | 6.38 | 41 | observed_rank |
| `krishna` | yes | कृष्णा | curated_entities | AK-NEI | 4.55 | 3,026 | observed_rank |
| `sharma` | no | -- | -- | -- | -- | -- | -- |
| `aditya` | yes | आदित्य | curated_entities | AK-NEI | 4.24 | 5,598 | observed_rank |
| `mera` | yes | मेरा | mined | Samanantar | 5.78 | 213 | observed_rank |
| `pyaar` | yes | प्यार | human_romanized | Dakshina | 5.68 | 299 | observed_rank |
| `prem` | yes | प्रेम | human_romanized | Dakshina | 5.40 | 535 | observed_rank |
| `maa` | no | -- | -- | -- | -- | -- | -- |
| `papa` | yes | पीएपीए | curated_entities | Wikidata | 4.79 | 1,946 | observed_rank |
| `dost` | no | -- | -- | -- | -- | -- | -- |
| `ghar` | no | -- | -- | -- | -- | -- | -- |

## English controls -- the accidental-overlap confound

Generic English password vocabulary. Any coverage here is accidental overlap from Aksharantar's transliteration subsources, and it is a confound the benchmark's English control must be read against -- not evidence of Indic awareness.

| Word | Present | Native form | Tier | Source | Priced by |
| --- | :---: | --- | --- | --- | --- |
| `password` | **yes** | पासवर्ड | human_romanized | Dakshina | observed_rank |
| `welcome` | no | -- | -- | -- | -- |
| `football` | **yes** | फुटबॉल | human_romanized | Dakshina | observed_rank |
| `qwerty` | **yes** | क्वेर्टी | curated_other | Existing | tier_fallback |
| `letmein` | no | -- | -- | -- | -- |
| `monkey` | **yes** | मोंके | curated_other | Existing | tier_fallback |
| `dragon` | **yes** | ड्रैगन | human_romanized | Dakshina | observed_rank |
| `master` | no | -- | -- | -- | -- |
| `shadow` | **yes** | शादोव | human_romanized | Dakshina | tier_fallback |
| `superman` | **yes** | सुपरमैन | human_romanized | Dakshina | tier_fallback |

## Words absent from the dictionary

These are not filtering artefacts -- they are absent from Aksharantar's Hindi
split entirely, at source. Aksharantar is a transliteration benchmark built from
named entities and mined pairs, not a lexicon of what people type.

  `namaste`, `namaskar`, `dhanyavaad`, `shukriya`, `pranam`, `maa`, `bhai`, `behen`, `beta`, `beti`, `dada`, `dadi`, `nani`, `chacha`, `chachi`, `mama`, `mami`, `bua`, `didi`, `ishq`, `mohabbat`, `dil`, `jaan`, `dost`, `dosti`, `khushi`, `gham`, `sapna`, `umeed`, `ghar`, `paani`, `khana`, `roti`, `doodh`, `kitab`, `school`, `gaadi`, `paisa`, `kaam`, `raat`, `shaam`, `duniya`, `zindagi`, `raasta`, `gaon`, `desh`, `phool`, `aasman`, `samundar`, `barish`, `hawa`, `aag`, `chota`, `meetha`, `garam`, `thanda`, `jaldi`, `chalo`, `suno`, `bolo`, `tera`, `hamara`, `apna`, `kuch`, `bahut`, `hindustan`, `india`, `dilli`, `bangalore`, `lucknow`, `ganga`, `himalaya`, `rahul`, `rohit`, `shiva`, `ganesh`, `hanuman`, `ram`, `sita`, `radha`, `laxmi`, `pooja`, `neha`, `anjali`, `kavita`, `sunita`, `deepak`, `manish`, `ramesh`, `ravi`, `ajay`, `vijay`, `anil`, `sharma`, `verma`, `nair`, `iyer`, `shah`, `joshi`, `bose`, `roy`

## Accidental hits by token length

The probability that a random lower-case string of length L is a dictionary key.
This is what `matching.min_substring_length` is calibrated from: below the length
where a hit becomes surprising, a match is close to no evidence at all.

| Length | Entries | Search space | P(random string is a key) |
| ---: | ---: | ---: | ---: |
| 3 | 6,999 | 17,576 | 3.982e-01 |
| 4 | 24,967 | 456,976 | 5.464e-02 |
| 5 | 65,834 | 11,881,376 | 5.541e-03 |
| 6 | 70,278 | 308,915,776 | 2.275e-04 |
| 7 | 29,925 | 8,031,810,176 | 3.726e-06 |
| 8 | 28,855 | 208,827,064,576 | 1.382e-07 |
| 9 | 23,579 | 5,429,503,678,976 | 4.343e-09 |
| 10 | 17,689 | 141,167,095,653,376 | 1.253e-10 |

## How to read this

Coverage is the ceiling on everything the guess model can do. A word the
dictionary does not hold cannot be recognised however good the scoring is, and
the missing words here are among the commonest in the language. Any benchmark
result for the Indic categories should be read against this table first.

