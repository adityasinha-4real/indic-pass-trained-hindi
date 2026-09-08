# Transliteration evaluation -- indicpass-hin-v1

- **Generated:** 2026-09-06T18:53:52+00:00
- **Git commit:** `8a09173ef35109e4d0310c7a8b118a9afb021f5b`
- **Model:** `models/final/indicpass-hin-v1` (bundle)
- **Dataset:** `data/processed/aksharantar/hin/test.jsonl`
- **Split:** `test` -- **held-out**
- **Records:** 10,112

## Headline result

| Metric | Value |
| --- | ---: |
| Test CER | 0.1084 |
| Test exact match | 0.5618 (56.18%) |
| Records | 10,112 |

## Validation numbers are not this result

Validation CER is what the best checkpoint was chosen by. It is a model-selection statistic, NOT a held-out result, and must not be reported as the headline accuracy of this model.

| Metric | Split | Value | Role |
| --- | --- | ---: | --- |
| CER | validation | 0.10482093997433352 | model selection |
| CER | test | 0.1084 | held-out result |

## Lengths

| Series | min | mean | max |
| --- | ---: | ---: | ---: |
| source | 2 | 7.869 | 26 |
| target | 1 | 6.871 | 20 |
| prediction | 1 | 6.859 | 20 |

## Runtime

- 90.41 s on CPU (111.85 records/s)
- greedy decoding, batch 128, max 64 characters

## Samples

| source | target | prediction | exact |
| --- | --- | --- | :---: |
| `maitrologist` | मैट्रोलॉजिस्ट | मैट्रोलॉजिस्ट | yes |
| `phwcs` | पीएचडब्ल्यूसीएस | फ्व्स् | no |
| `pratidwandiyon` | प्रतिद्वन्दियों | प्रतिद्वंद्वियों | no |
| `pratiyukti` | प्रतियुक्ति | प्रतियुक्ति | yes |
| `eksisatens` | एक्सिसटेंस | एक्सीसेटेंस | no |
| `filmnirmata` | फ़िल्मनिर्माता | फिल्मनिर्माता | no |
| `adrgh` | अद्र्घ | एडीआरएफ | no |
| `ladhege` | लड़ेगे | लढेगे | no |
| `administresh` | एडमिनिस्ट्रेश | एडमिनिस्ट्रेश | yes |
| `shiwalapurwa` | शिवालापुरवा | शिवालापुरवा | yes |
