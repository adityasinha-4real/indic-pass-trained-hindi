"""The standard record schema, stable ids and hash-based split assignment."""

from __future__ import annotations

import pytest

from indicpass.records import (
    FIELD_ORDER,
    REQUIRED_FIELDS,
    Record,
    assign_split,
    read_jsonl,
    stable_id,
    write_jsonl,
)

RATIOS = {"train": 0.98, "validation": 0.01, "test": 0.01}


def make(
    source: str = "namaste",
    target: str = "नमस्ते",
    split: str = "train",
    subsource: str = "",
) -> Record:
    return Record(
        language="hin",
        script="Deva",
        source_text=source,
        target_text=target,
        dataset_source="aksharantar",
        subsource=subsource,
        split=split,
    )


def test_record_id_is_derived_and_stable():
    record = make()
    assert record.record_id == stable_id("hin", "namaste", "नमस्ते")
    assert make().record_id == record.record_id


def test_record_id_is_hardcoded_so_regressions_are_visible():
    # If this changes, every previously processed dataset is invalidated.
    assert stable_id("hin", "namaste", "नमस्ते") == "f5a22b75af6e6d74"


def test_different_content_gives_different_ids():
    assert make().record_id != make(source="namaskar").record_id
    assert make().record_id != make(target="नमस्कार").record_id


def test_id_separator_prevents_field_boundary_collisions():
    # ("hi", "ab") and ("hia", "b") must not hash to the same value.
    assert stable_id("hi", "ab", "x") != stable_id("hia", "b", "x")


def test_explicit_record_id_is_preserved():
    assert Record(
        language="hin",
        script="Deva",
        source_text="a",
        target_text="ब",
        dataset_source="x",
        split="train",
        record_id="deadbeefdeadbeef",
    ).record_id == "deadbeefdeadbeef"


def test_to_dict_uses_the_documented_field_order():
    assert list(make().to_dict()) == list(FIELD_ORDER)


def test_round_trip_through_dict():
    record = make()
    assert Record.from_dict(record.to_dict()) == record


# -- subsource (provenance) ------------------------------------------------


def test_subsource_is_preserved_through_serialisation():
    record = make(subsource="Dakshina")
    assert record.subsource == "Dakshina"
    assert record.to_dict()["subsource"] == "Dakshina"
    assert Record.from_dict(record.to_dict()).subsource == "Dakshina"


def test_subsource_defaults_to_empty_not_none():
    # Sources that do not distinguish sub-corpora must still round-trip.
    assert make().subsource == ""
    assert make().to_dict()["subsource"] == ""


def test_subsource_does_not_change_the_record_id():
    """Provenance is not identity: the same pair from two sub-corpora is one pair.

    If this ever fails, deduplication silently stops working across
    sub-corpora and every previously computed id is invalidated.
    """
    assert make(subsource="Dakshina").record_id == make(subsource="Wikidata").record_id
    assert make(subsource="Dakshina").record_id == make().record_id
    assert make(subsource="AK-Freq").record_id == stable_id("hin", "namaste", "नमस्ते")


def test_subsource_is_optional_so_v1_records_still_load():
    v1 = {
        "record_id": "f5a22b75af6e6d74",
        "language": "hin",
        "script": "Deva",
        "source_text": "namaste",
        "target_text": "नमस्ते",
        "dataset_source": "aksharantar",
        "split": "train",
    }
    assert "subsource" not in v1
    assert Record.from_dict(v1) == make()


def test_required_fields_excludes_subsource_but_nothing_else():
    assert "subsource" not in REQUIRED_FIELDS
    assert set(REQUIRED_FIELDS) == set(FIELD_ORDER) - {"subsource"}


def test_null_subsource_normalises_to_empty_string():
    # Upstream nulls must not leak a None into the schema.
    assert Record.from_dict({**make().to_dict(), "subsource": None}).subsource == ""


# -- split assignment ------------------------------------------------------


def test_split_assignment_is_deterministic():
    record_id = stable_id("hin", "namaste", "नमस्ते")
    assert assign_split(record_id, RATIOS) == assign_split(record_id, RATIOS)


def test_split_assignment_only_returns_configured_names():
    for index in range(500):
        assert assign_split(stable_id("hin", f"w{index}", f"n{index}"), RATIOS) in RATIOS


def test_split_assignment_honours_the_configured_proportions():
    counts = {name: 0 for name in RATIOS}
    total = 20_000
    for index in range(total):
        counts[assign_split(stable_id("hin", f"w{index}", f"n{index}"), RATIOS)] += 1

    for name, expected in RATIOS.items():
        assert counts[name] / total == pytest.approx(expected, abs=0.005)


def test_split_assignment_does_not_depend_on_input_order():
    ids = [stable_id("hin", f"w{i}", f"n{i}") for i in range(200)]
    forward = {i: assign_split(i, RATIOS) for i in ids}
    backward = {i: assign_split(i, RATIOS) for i in reversed(ids)}
    assert forward == backward


def test_unnormalised_ratios_are_accepted():
    assert assign_split(stable_id("hin", "a", "ब"), {"train": 98, "test": 2}) in {"train", "test"}


def test_empty_ratios_are_rejected():
    with pytest.raises(ValueError, match="at least one split ratio"):
        assign_split("00000000", {})


# -- jsonl io --------------------------------------------------------------


def test_jsonl_round_trip_preserves_native_script_and_provenance(tmp_path):
    records = [
        make(subsource="Dakshina"),
        make(source="kaise", target="कैसे", subsource="Wikidata"),
    ]
    path = tmp_path / "train.jsonl"

    assert write_jsonl(path, records) == 2
    text = path.read_text(encoding="utf-8")
    # ensure_ascii=False keeps the file readable when eyeballing Indic data.
    assert "नमस्ते" in text
    assert "Dakshina" in text
    assert [Record.from_dict(row) for row in read_jsonl(path)] == records


def test_read_jsonl_reports_the_offending_line_number(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{"a": 1}\nnot json\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"broken\.jsonl:2"):
        list(read_jsonl(path))
