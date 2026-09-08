"""scripts/evaluate.py -- the reporting logic, without loading a model.

The parts worth testing here are the ones that decide what a reader believes:
whether a number is labelled held-out, and whether the validation figure is
kept visibly separate from it. Decoding itself is `Trainer.evaluate`'s code
path and is covered by tests/test_metrics.py.
"""

from __future__ import annotations

import argparse
import json
from typing import ClassVar

import pytest

import evaluate
from indicpass.config import load_config


class FakeTokenizer:
    source_vocab_size = 30
    target_vocab_size = 75
    metadata: ClassVar[dict] = {"language": "hin", "fitted_on": "train"}


class FakeLoaded:
    kind = "bundle"
    identifier = "indicpass-hin-v1"
    tokenizer = FakeTokenizer()

    def __init__(self, metadata=None, path=None):
        self.metadata = metadata if metadata is not None else {"metrics": {"best_cer": 0.1048}}
        self.path = path or load_config().root / "models/final/indicpass-hin-v1"


def make_args(**overrides) -> argparse.Namespace:
    defaults = {
        "split": "test",
        "limit": None,
        "samples": 2,
        "batch_size": 128,
        "max_length": 64,
        "languages": ["hin"],
        "output": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def build(**overrides):
    config = load_config()
    sources = overrides.pop("sources", ["namaste", "kaise", "ho"])
    targets = overrides.pop("targets", ["नमस्ते", "कैसे", "हो"])
    predictions = overrides.pop("predictions", ["नमस्ते", "कैसा", "हो"])
    loaded = overrides.pop("loaded", FakeLoaded())

    return evaluate.build_report(
        config=config,
        args=make_args(**overrides),
        loaded=loaded,
        split_path=config.root / "data/processed/aksharantar/hin/test.jsonl",
        sources=sources,
        targets=targets,
        predictions=predictions,
        seconds=1.5,
        device="CPU",
    )


# -- reading a split -------------------------------------------------------


def test_load_split_reads_parallel_lists(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"source_text": s, "target_text": t}, ensure_ascii=False)
            for s, t in [("namaste", "नमस्ते"), ("kaise", "कैसे")]
        )
        + "\n",
        encoding="utf-8",
    )
    sources, targets = evaluate.load_split(path)
    assert sources == ["namaste", "kaise"]
    assert targets == ["नमस्ते", "कैसे"]


def test_load_split_skips_incomplete_records(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        json.dumps({"source_text": "namaste", "target_text": "नमस्ते"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"source_text": "", "target_text": "x"})
        + "\n",
        encoding="utf-8",
    )
    sources, _ = evaluate.load_split(path)
    assert sources == ["namaste"]


def test_load_split_honours_the_limit(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"source_text": f"w{i}", "target_text": "क"}) for i in range(10)
        )
        + "\n",
        encoding="utf-8",
    )
    sources, _ = evaluate.load_split(path, limit=3)
    assert len(sources) == 3


def test_load_split_rejects_an_empty_file(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable records"):
        evaluate.load_split(path)


# -- the held-out labelling ------------------------------------------------


def test_the_test_split_is_marked_held_out():
    assert build()["evaluation"]["held_out"] is True


def test_any_other_split_is_marked_not_held_out():
    """Pointing this at validation must not silently produce a "held-out" report."""
    assert build(split="validation")["evaluation"]["held_out"] is False


def test_the_validation_number_is_labelled_as_model_selection():
    selection = build()["selection_metrics"]
    assert selection["split"] == "validation"
    assert selection["role"] == "model selection"
    assert selection["cer"] == pytest.approx(0.1048)
    assert "NOT a held-out result" in selection["note"]


def test_the_two_numbers_are_reported_separately():
    """The point of the script: they must never collapse into one field."""
    report = build()
    assert report["metrics"]["cer"] != report["selection_metrics"]["cer"]


def test_a_model_without_recorded_metrics_reports_none_rather_than_guessing():
    report = build(loaded=FakeLoaded(metadata={}))
    assert report["selection_metrics"]["cer"] is None


# -- metrics and provenance ------------------------------------------------


def test_metrics_match_the_predictions():
    report = build()
    assert report["metrics"]["count"] == 3
    assert report["metrics"]["exact_match"] == pytest.approx(2 / 3)
    assert 0 < report["metrics"]["cer"] < 1


def test_average_lengths_are_reported():
    lengths = build()["lengths"]
    # Reported to 4 decimal places, so compare at that resolution.
    assert lengths["average_source_length"] == pytest.approx((7 + 5 + 2) / 3, abs=1e-4)
    assert lengths["source"]["min"] == 2
    assert lengths["source"]["max"] == 7


def test_runtime_is_reported_with_a_rate():
    runtime = build()["runtime"]
    assert runtime["seconds"] == pytest.approx(1.5)
    assert runtime["records_per_second"] == pytest.approx(2.0)
    assert runtime["decoding"] == "greedy"


def test_provenance_identifies_the_model_dataset_and_commit():
    report = build()
    assert report["model"]["identifier"] == "indicpass-hin-v1"
    assert report["dataset"]["file"].endswith("test.jsonl")
    assert report["git_commit"]  # "unknown" outside a checkout, but never absent


def test_a_truncated_run_says_so():
    report = build(limit=3)
    assert report["evaluation"]["truncated"] is True
    assert report["evaluation"]["limit"] == 3


def test_a_full_run_is_not_marked_truncated():
    assert build()["evaluation"]["truncated"] is False


def test_samples_are_capped_and_flag_exact_matches():
    samples = build(samples=2)["samples"]
    assert len(samples) == 2
    assert samples[0]["exact"] is True
    assert samples[1]["exact"] is False


def test_the_report_is_json_serialisable():
    json.dumps(build(), ensure_ascii=False)


# -- markdown --------------------------------------------------------------


def test_markdown_states_both_numbers_and_which_is_which():
    text = evaluate.render_markdown(build())
    assert "held-out" in text
    assert "model selection" in text
    assert "Validation numbers are not this result" in text


def test_markdown_marks_a_non_test_split_as_not_held_out():
    text = evaluate.render_markdown(build(split="validation"))
    assert "not held out" in text
