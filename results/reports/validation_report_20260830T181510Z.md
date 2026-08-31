# IndicPass validation report

- **Generated:** 2026-08-30T18:15:10+00:00
- **Input:** `data\processed`
- **Records:** 1,315,562
- **Result:** PASSED

## Summary

| Language | Records | Unique sources | Duplicate ratio | Target script OK | Source Roman OK | Status |
| --- | ---: | ---: | ---: | ---: | ---: | :--- |
| hin (Hindi) | 1,315,562 | 1,080,299 | 0.0000 | 1.0000 | 1.0000 | PASS |

## Split overlap

Shared source spellings between split pairs, as a fraction of unique sources.
`train_validation` and `train_test` are contamination and are hard gates.
`validation_test` involves no training data, so it is reported, not gated.

| Language | Pair | Shared sources | Ratio | Gate |
| --- | --- | ---: | ---: | :--- |
| hin | train_validation | 0 | 0.000000 | **gated at 0.0** |
| hin | train_test | 0 | 0.000000 | **gated at 0.0** |
| hin | validation_test | 138 | 0.000128 | reported only |

## hin -- Hindi

- Splits: {'test': 10112, 'train': 1299143, 'validation': 6307}
- Source length min/mean/max: 1 / 8.67 / 32
- Target length min/mean/max: 1 / 7.78 / 28
- Ambiguous sources (one Roman form, several native forms): 143,972
- Sources appearing in more than one split: 138

**Provenance by subsource**

| Subsource | Records | Share |
| --- | ---: | ---: |
| IndicCorp | 958,605 | 72.87% |
| Samanantar | 154,090 | 11.71% |
| Existing | 131,771 | 10.02% |
| Dakshina | 31,293 | 2.38% |
| Wikidata | 24,983 | 1.90% |
| AK-Freq | 12,806 | 0.97% |
| AK-NEI | 1,188 | 0.09% |
| AK-NEF | 826 | 0.06% |

**Samples**

| source | target | split |
| --- | --- | --- |
| `maitrologist` | मैट्रोलॉजिस्ट | test |
| `phwcs` | पीएचडब्ल्यूसीएस | test |
| `pratidwandiyon` | प्रतिद्वन्दियों | test |
| `pratiyukti` | प्रतियुक्ति | test |
| `eksisatens` | एक्सिसटेंस | test |
