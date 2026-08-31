"""Configuration loading and language resolution."""

from __future__ import annotations

import pytest

from indicpass.config import ConfigError, find_project_root, load_config


@pytest.fixture(scope="module")
def config():
    return load_config()


def test_project_root_has_the_expected_layout():
    root = find_project_root()
    for expected in ("config", "scripts", "src", "requirements"):
        assert (root / expected).is_dir(), f"missing {expected}/"


def test_default_targets_are_the_five_launch_languages(config):
    assert [language.code for language in config.resolve_languages(None)] == [
        "hin",
        "tam",
        "tel",
        "kan",
        "mal",
    ]


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("hin", "hin"),
        ("hi", "hin"),
        ("Hindi", "hin"),
        ("HINGLISH", "hin"),
        ("ta", "tam"),
        ("tanglish", "tam"),
        ("telugu", "tel"),
        ("Kanglish", "kan"),
        ("ml", "mal"),
    ],
)
def test_language_aliases_normalise_to_iso_639_3(config, spelling, expected):
    assert config.language(spelling).code == expected


def test_unknown_language_names_the_configured_ones(config):
    with pytest.raises(ConfigError, match="Unknown language"):
        config.language("klingon")


def test_resolve_languages_collapses_duplicates_and_keeps_order(config):
    resolved = config.resolve_languages(["tamil", "hin", "ta", "hi"])
    assert [language.code for language in resolved] == ["tam", "hin"]


def test_every_configured_path_is_relative_and_under_the_root(config):
    for key in config.project["paths"]:
        resolved = config.path(key)
        assert resolved.is_relative_to(config.root), f"paths.{key} escapes the project root"


def test_languages_declare_distinct_non_overlapping_scripts(config):
    seen: list[tuple[str, tuple[int, int]]] = []
    for language in config.languages.values():
        for start, end in language.unicode_ranges:
            for other_code, (other_start, other_end) in seen:
                overlaps = start <= other_end and other_start <= end
                assert not overlaps, f"{language.code} overlaps {other_code}"
            seen.append((language.code, (start, end)))


def test_default_source_is_configured(config):
    source = config.source()
    assert source["repo_id"] == "ai4bharat/Aksharantar"
    assert source["type"] == "huggingface"
