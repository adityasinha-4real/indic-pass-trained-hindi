"""Split-overlap measurement and gating.

The distinction under test: a source spelling shared between train and an
evaluation split is contamination and must fail the run; the same spelling
shared between validation and test is not, and must not.
"""

from __future__ import annotations

import pytest

from indicpass.config import load_config
from indicpass.records import Record
from validate_dataset import LanguageAudit, evaluate

THRESHOLDS = {
    "max_train_validation_leakage_ratio": 0.0,
    "max_train_test_leakage_ratio": 0.0,
    "max_validation_test_overlap_ratio": None,
}


@pytest.fixture(scope="module")
def config():
    return load_config()


def audit_of(config, pairs: list[tuple[str, str, str]]) -> dict:
    """Run an audit over ``(source, target, split)`` triples and summarise."""
    audit = LanguageAudit(config.language("hin"), config)
    for source, target, split in pairs:
        record = Record(
            language="hin",
            script="Deva",
            source_text=source,
            target_text=target,
            dataset_source="aksharantar",
            split=split,
        )
        audit.inspect(record.to_dict(), f"{split}.jsonl", 0)
    return audit.summary()


CLEAN = [
    ("namaste", "नमस्ते", "train"),
    ("kaise", "कैसे", "train"),
    ("dhanyavaad", "धन्यवाद", "validation"),
    ("shukriya", "शुक्रिया", "test"),
]


# -- clean splits ----------------------------------------------------------


def test_clean_splits_report_no_overlap_and_pass(config):
    summary = audit_of(config, CLEAN)
    overlap = summary["split_overlap"]

    assert overlap["train_validation"]["count"] == 0
    assert overlap["train_test"]["count"] == 0
    assert overlap["validation_test"]["count"] == 0
    assert summary["sources_in_multiple_splits"] == 0
    assert evaluate(summary, THRESHOLDS) == []


# -- train <-> validation leakage (gated) ----------------------------------


def test_train_validation_leakage_is_counted_and_fails(config):
    summary = audit_of(config, [*CLEAN, ("namaste", "नमस्कार", "validation")])
    overlap = summary["split_overlap"]

    assert overlap["train_validation"]["count"] == 1
    assert overlap["train_test"]["count"] == 0
    assert overlap["validation_test"]["count"] == 0
    assert overlap["train_validation"]["gated"] is True

    failures = evaluate(summary, THRESHOLDS)
    assert len(failures) == 1
    assert "max_train_validation_leakage_ratio" in failures[0]


# -- train <-> test leakage (gated) ----------------------------------------


def test_train_test_leakage_is_counted_and_fails(config):
    summary = audit_of(config, [*CLEAN, ("kaise", "कैसा", "test")])
    overlap = summary["split_overlap"]

    assert overlap["train_test"]["count"] == 1
    assert overlap["train_validation"]["count"] == 0
    assert overlap["train_test"]["gated"] is True

    failures = evaluate(summary, THRESHOLDS)
    assert len(failures) == 1
    assert "max_train_test_leakage_ratio" in failures[0]


# -- validation <-> test overlap (reported, NOT gated) ---------------------


def test_validation_test_overlap_is_reported_but_does_not_fail(config):
    """This is the Aksharantar case: 138 spellings shared, train clean."""
    summary = audit_of(config, [*CLEAN, ("shukriya", "शुकरिया", "validation")])
    overlap = summary["split_overlap"]

    assert overlap["validation_test"]["count"] == 1
    assert overlap["validation_test"]["ratio"] > 0
    assert overlap["validation_test"]["gated"] is False
    assert summary["sources_in_multiple_splits"] == 1

    # Measured, visible in the report -- and passing.
    assert evaluate(summary, THRESHOLDS) == []


def test_validation_test_overlap_can_be_gated_when_asked(config):
    summary = audit_of(config, [*CLEAN, ("shukriya", "शुकरिया", "validation")])
    strict = {**THRESHOLDS, "max_validation_test_overlap_ratio": 0.0}

    failures = evaluate(summary, strict)
    assert len(failures) == 1
    assert "max_validation_test_overlap_ratio" in failures[0]


# -- combinations ----------------------------------------------------------


def test_a_source_in_all_three_splits_counts_in_every_pair(config):
    summary = audit_of(
        config,
        [
            ("namaste", "नमस्ते", "train"),
            ("namaste", "नमस्कार", "validation"),
            ("namaste", "नमसते", "test"),
        ],
    )
    overlap = summary["split_overlap"]

    assert overlap["train_validation"]["count"] == 1
    assert overlap["train_test"]["count"] == 1
    assert overlap["validation_test"]["count"] == 1
    # ...but it is one source spelling, not three.
    assert summary["sources_in_multiple_splits"] == 1

    failures = evaluate(summary, THRESHOLDS)
    assert len(failures) == 2  # both train pairs, not the validation/test one


def test_both_train_pairs_fail_independently(config):
    summary = audit_of(
        config,
        [
            *CLEAN,
            ("namaste", "नमस्कार", "validation"),
            ("kaise", "कैसा", "test"),
        ],
    )
    failures = " | ".join(evaluate(summary, THRESHOLDS))
    assert "max_train_validation_leakage_ratio" in failures
    assert "max_train_test_leakage_ratio" in failures


def test_overlap_ratio_is_per_unique_source_not_per_record(config):
    # 4 unique sources, 1 of them leaked -> 0.25, regardless of row count.
    summary = audit_of(config, [*CLEAN, ("namaste", "नमस्कार", "validation")])
    assert summary["unique_sources"] == 4
    assert summary["split_overlap"]["train_validation"]["ratio"] == pytest.approx(0.25)


# -- threshold handling ----------------------------------------------------


def test_absent_threshold_is_not_checked(config):
    summary = audit_of(config, [*CLEAN, ("namaste", "नमस्कार", "validation")])
    assert evaluate(summary, {}) == []


def test_null_threshold_is_not_checked(config):
    summary = audit_of(config, [*CLEAN, ("namaste", "नमस्कार", "validation")])
    assert evaluate(summary, {"max_train_validation_leakage_ratio": None}) == []


def test_the_shipped_config_gates_train_pairs_and_not_validation_test(config):
    """Guards against the thresholds being loosened in dataset.yaml by accident."""
    thresholds = config.validation["thresholds"]

    assert thresholds["max_train_validation_leakage_ratio"] == 0.0
    assert thresholds["max_train_test_leakage_ratio"] == 0.0
    assert thresholds.get("max_validation_test_overlap_ratio") is None
    # The old single gate must be gone, not merely unused.
    assert "max_split_leakage_ratio" not in thresholds


def test_unknown_split_names_are_flagged_and_do_not_corrupt_pair_counts(config):
    summary = audit_of(config, [*CLEAN, ("namaste", "नमस्कार", "holdout")])

    assert summary["issues"].get("unknown_split_name") == 1
    # "holdout" shares the overflow bit, so it registers as multi-split...
    assert summary["sources_in_multiple_splits"] == 1
    # ...but must not be miscounted as a train/validation or train/test pair.
    assert summary["split_overlap"]["train_validation"]["count"] == 0
    assert summary["split_overlap"]["train_test"]["count"] == 0
    assert evaluate(summary, THRESHOLDS) == []
