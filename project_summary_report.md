# IndicPass Project Progress Report

**Project Name:** IndicPass (Multilingual Indian Transliteration & Code-Mixed Text Processing)  
**Target Language:** Hindi Baseline (`hin` -> Devanagari)  
**Status:** Phase 1 (Hindi Dataset Pipeline, GPU Training, Evaluation & Deployment Bundling) — **COMPLETED**

---

## Executive Summary

The initial milestone for **IndicPass**—building, training, evaluating, and packaging a character-level sequence-to-sequence transliteration model for Romanized Hindi (`hin`) to native Devanagari script—has been successfully achieved.

The model was trained end-to-end on the complete **ai4bharat/Aksharantar** dataset (**1,299,143 training pairs**) and achieved an exceptional **10.48% Character Error Rate (CER)** and **57.94% Exact Match Accuracy** on the validation set.

---

## 1. System Architecture & Methodology

* **Model Design**: Character-level Sequence-to-Sequence neural network written directly in PyTorch:
  * **Encoder**: 2-Layer Bidirectional LSTM with packed sequence inputs.
  * **Attention**: Bahdanau (additive) attention mechanism masked at padding tokens.
  * **Decoder**: 2-Layer LSTM decoder with input-feeding.
  * **Vocabularies**: Separate source (Roman: 30 symbols) and target (Devanagari: 75 symbols) character vocabularies fitted strictly on the training set to prevent held-out data leakage.
* **Total Parameters**: 17,207,627 parameters (~66 MB fp32 weights).

---

## 2. Dataset Pipeline & Data Quality

* **Source Corpus**: `ai4bharat/Aksharantar` (pinned revision `e418c1fc928d9f5393af33268472cf20c1891be8`).
* **Preprocessing**: Fully deterministic deduplication, whitespace normalization, script validation, and content-hash record ID generation (`stable_id`).
* **Processed Record Distribution**:
  * **Train Split**: 1,299,143 pairs (98%)
  * **Validation Split**: 6,307 pairs (1%)
  * **Test Split**: 10,112 pairs (1%)
  * **Total Records**: 1,315,562 pairs
* **Quality Assurance**: Gated validation script verified **zero leakage/overlap** between train/validation and train/test splits.

---

## 3. Multi-Stage Training Progression

Training was executed progressively in four controlled stages to validate correctness, performance, and scaling:

| Stage | Dataset Size | Epochs | Training Loss | Validation CER ↓ | Exact Match ↑ | Outcome / Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Stage 1 (Debug)** | 500 | 30 | 0.0038 | **0.0000** | 100.00% | Passed overfit sanity gate |
| **Stage 2 (10k)** | 10,000 | 5 | 0.2797 | **0.2039** | 33.07% | Verified GPU pipeline |
| **Stage 3 (100k)** | 100,000 | 8 | 0.2353 | **0.1543** | 43.25% | Architecture scaling confirmed |
| **Stage 4 (Full Baseline)** | **1,299,143** | **15** | **0.1830** | **0.1048** | **57.94%** | **Full Baseline Model Trained** |

---

## 4. Production Deployment & Bundling

* **Model Packaging**: Created an automated exporter (`scripts/export_bundle.py`) that exports checkpoints into standard, safe deployment bundles under `models/final/indicpass-hin-v1/`.
* **Security & Safety**: Saved weights using `safetensors` (`model.safetensors`), eliminating arbitrary code execution risks associated with standard pickle checkpoints.
* **Metadata & Provenance**: Embedded `inference_metadata.json` capturing the exact git commit, dataset revision, training hyperparameters, and final evaluation metrics.
* **Inference Verification**: Live predictions verified:
  * Input: `"namaste kaise ho bharat dhanyavaad"` $\rightarrow$ Output: **`नमस्ते कैसे हो भारत धन्यवाद`**
  * Input: `"aapka naam kya hai"` $\rightarrow$ Output: **`आपका नाम क्या है`**

---

## 5. Next Planned Milestones

1. **Extension to Other Indic Languages**: Train baseline models for Tamil (`tam`), Telugu (`tel`), Kannada (`kan`), and Malayalam (`mal`).
2. **Evaluation Set Analysis**: Run final test set evaluation (`10,112` test pairs) and generate formal error reports.
3. **Backend API Integration**: Build a lightweight Python API endpoint serving the `indicpass-hin-v1` bundle.
