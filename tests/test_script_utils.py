"""Unicode / writing-system helpers.

The strings here are short real words in each target script -- enough to prove
a script check distinguishes Devanagari from Tamil, and native text from
Romanized text.
"""

from __future__ import annotations

import pytest

from indicpass.config import load_config
from indicpass.script_utils import (
    ascii_ratio,
    collapse_whitespace,
    detect_language,
    is_probably_romanized,
    normalize,
    script_ratio,
)

NATIVE = {
    "hin": "नमस्ते",
    "tam": "வணக்கம்",
    "tel": "నమస్కారం",
    "kan": "ನಮಸ್ಕಾರ",
    "mal": "നമസ്കാരം",
}


@pytest.fixture(scope="module")
def config():
    return load_config()


def ratio_for(config, text: str, code: str) -> float:
    language = config.language(code)
    return script_ratio(
        text,
        language.unicode_ranges,
        neutral_codepoints=config.neutral_codepoints,
        neutral_categories=config.neutral_categories,
    )


@pytest.mark.parametrize("code", sorted(NATIVE))
def test_native_text_scores_one_in_its_own_script(config, code):
    assert ratio_for(config, NATIVE[code], code) == 1.0


@pytest.mark.parametrize("code", sorted(NATIVE))
def test_native_text_scores_zero_in_every_other_script(config, code):
    for other in NATIVE:
        if other != code:
            assert ratio_for(config, NATIVE[code], other) == 0.0


@pytest.mark.parametrize("code", sorted(NATIVE))
def test_romanized_text_never_counts_as_native_script(config, code):
    assert ratio_for(config, "namaste kaise ho", code) == 0.0


def test_empty_and_punctuation_only_text_scores_zero(config):
    # "No evidence" must not read as "valid" -- otherwise junk rows pass.
    assert ratio_for(config, "", "hin") == 0.0
    assert ratio_for(config, "!!! ,, ??", "hin") == 0.0
    assert ratio_for(config, "123", "hin") == 0.0


def test_joiners_and_punctuation_do_not_penalise_valid_text(config):
    # ZWNJ is structurally required inside some Devanagari conjuncts.
    assert ratio_for(config, "नमस्ते‌, नमस्ते!", "hin") == 1.0


def test_mixed_script_scores_between_zero_and_one(config):
    ratio = ratio_for(config, "नमस्ते hello", "hin")
    assert 0.0 < ratio < 1.0


def test_ascii_ratio_ignores_digits_and_punctuation():
    assert ascii_ratio("namaste") == 1.0
    assert ascii_ratio("web-2.0!") == 1.0
    assert ascii_ratio("नमस्ते") == 0.0
    assert ascii_ratio("") == 0.0


def test_is_probably_romanized():
    assert is_probably_romanized("vanakkam epdi iruka")
    assert not is_probably_romanized("வணக்கம்")


def test_collapse_whitespace():
    assert collapse_whitespace("  kaise   ho \n") == "kaise ho"


def test_normalize_is_idempotent_and_makes_equal_strings_compare_equal():
    # Same word, decomposed vs. composed: must deduplicate to one form.
    composed = "नमस्ते"
    decomposed = normalize(composed, "NFD")
    assert normalize(decomposed, "NFC") == normalize(composed, "NFC")
    assert normalize(normalize(composed)) == normalize(composed)


@pytest.mark.parametrize("code", sorted(NATIVE))
def test_detect_language_identifies_each_script(config, code):
    detected = detect_language(NATIVE[code], config)
    assert detected is not None
    assert detected.code == code


def test_detect_language_returns_none_for_romanized_input(config):
    assert detect_language("namaste kaise ho", config) is None
