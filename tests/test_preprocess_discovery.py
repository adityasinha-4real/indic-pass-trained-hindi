"""Raw-file discovery, split routing and field mapping.

These exercise the parts of ``preprocess_dataset.py`` that depend on how an
upstream repository happens to lay its files out -- the parts most likely to
break silently when a source changes. The layout mirrored here is Aksharantar's
real one, verified against the downloaded Hindi archive.
"""

from __future__ import annotations

import pytest

from indicpass.config import load_config
from preprocess_dataset import (
    detect_split,
    extract_subsource,
    find_language_files,
    pick_field,
)


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture
def raw_tree(tmp_path):
    """Aksharantar's layout after download + extraction, plus HF cache noise."""
    (tmp_path / "extracted" / "hin").mkdir(parents=True)
    for name in ("hin_train.json", "hin_valid.json", "hin_test.json"):
        (tmp_path / "extracted" / "hin" / name).write_text("{}\n", encoding="utf-8")
    (tmp_path / "hin.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    # snapshot_download leaves this next to the data; it is not dataset content.
    cache = tmp_path / ".cache" / "huggingface" / "download"
    cache.mkdir(parents=True)
    (cache / "hin.zip.metadata").write_text("x", encoding="utf-8")
    (tmp_path / ".cache" / "hin_notes.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_extracted_files_are_preferred_over_their_archive(config, raw_tree):
    """The archive and its contents both match -- reading both would double every record."""
    found = find_language_files(raw_tree, config.language("hin"), "aksharantar")

    assert [path.name for path in found] == [
        "hin_test.json",
        "hin_train.json",
        "hin_valid.json",
    ]
    assert not any(path.suffix == ".zip" for path in found)


def test_archive_is_used_when_nothing_has_been_extracted(config, tmp_path):
    (tmp_path / "hin.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    found = find_language_files(tmp_path, config.language("hin"), "aksharantar")
    assert [path.name for path in found] == ["hin.zip"]


def test_hidden_tool_directories_are_ignored(config, raw_tree):
    found = find_language_files(raw_tree, config.language("hin"), "aksharantar")
    assert not any(part.startswith(".") for path in found for part in path.parts)


def test_other_languages_are_not_picked_up(config, raw_tree):
    assert find_language_files(raw_tree, config.language("tam"), "aksharantar") == []


def test_missing_directory_is_not_an_error(config, tmp_path):
    assert find_language_files(tmp_path / "nope", config.language("hin"), "aksharantar") == []


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("hin_train.json", "train"),
        ("hin_valid.json", "validation"),  # upstream says "valid", we say "validation"
        ("hin_test.json", "test"),
        ("hin.zip!hin_valid.json", "validation"),
        ("something_else.json", None),
    ],
)
def test_split_markers_map_upstream_names_to_ours(config, filename, expected):
    markers = config.source("aksharantar")["split_markers"]
    assert detect_split(filename, markers) == expected


def test_field_map_resolves_a_real_aksharantar_record(config):
    # Verbatim shape of a record from the downloaded hin_train.json.
    record = {
        "unique_identifier": "hin1",
        "native word": "जन्मदिवस",
        "english word": "janamdivas",
        "source": "Dakshina",
        "score": None,
    }
    field_map = config.source("aksharantar")["field_map"]

    assert pick_field(record, field_map["source_text"]) == "janamdivas"
    assert pick_field(record, field_map["target_text"]) == "जन्मदिवस"


def test_pick_field_treats_blank_and_missing_alike():
    assert pick_field({"source": "  "}, ["source", "src"]) is None
    assert pick_field({}, ["source"]) is None
    assert pick_field({"SRC": "abc"}, ["src"]) == "abc"  # case-insensitive
    assert pick_field({"a": "", "b": "x"}, ["a", "b"]) == "x"  # falls through to the next


# -- subsource extraction --------------------------------------------------


def test_subsource_is_read_from_a_real_aksharantar_record(config):
    field_map = config.source("aksharantar")["field_map"]
    record = {
        "unique_identifier": "hin1",
        "native word": "जन्मदिवस",
        "english word": "janamdivas",
        "source": "Dakshina",
        "score": None,
    }
    assert extract_subsource(record, field_map, "janamdivas", "जन्मदिवस") == "Dakshina"


def test_subsource_is_empty_when_the_column_is_absent(config):
    field_map = config.source("aksharantar")["field_map"]
    record = {"english word": "namaste", "native word": "नमस्ते"}
    assert extract_subsource(record, field_map, "namaste", "नमस्ते") == ""


def test_subsource_column_that_actually_holds_the_text_is_discarded(config):
    """`source` is a candidate for both source_text and subsource.

    When a dataset uses it for the text, recording that text as provenance
    would be worse than recording nothing.
    """
    field_map = config.source("aksharantar")["field_map"]
    record = {"source": "namaste", "native word": "नमस्ते"}
    assert extract_subsource(record, field_map, "namaste", "नमस्ते") == ""


def test_subsource_is_trimmed_but_not_lowercased(config):
    field_map = config.source("aksharantar")["field_map"]
    record = {"english word": "a", "native word": "ब", "source": "  AK-Freq  "}
    # "AK-Freq" is a proper name; case is meaningful.
    assert extract_subsource(record, field_map, "a", "ब") == "AK-Freq"
