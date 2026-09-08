"""The zxcvbn adapter: the numbers it carries, and the content it must not."""

from __future__ import annotations

import json

import pytest

from indicpass.password.baseline import (
    BaselineEstimate,
    BaselineUnavailable,
    PasswordStrengthBaseline,
    load_baseline,
)

# The passwords used here are textbook examples and deliberately obvious --
# they exist to prove the adapter drops content, so they must be recognisable
# in a JSON dump if it ever fails to.
LEAKY = "sharma2024"


# -- the interface ---------------------------------------------------------


def test_the_interface_cannot_be_instantiated_without_an_estimate():
    with pytest.raises(TypeError):
        PasswordStrengthBaseline()  # type: ignore[abstract]


def test_an_unknown_implementation_is_refused_with_the_known_ones():
    with pytest.raises(BaselineUnavailable, match="Available:"):
        load_baseline("guesswork")


def test_an_estimate_serialises_to_the_documented_shape():
    payload = BaselineEstimate(
        guesses=1000.0, log10_guesses=3.0, score=1, patterns=("dictionary",)
    ).to_dict()
    assert payload == {
        "guesses": 1000.0,
        "log10_guesses": 3.0,
        "score": 1,
        "patterns": ["dictionary"],
        "feedback": [],
    }


# -- zxcvbn ----------------------------------------------------------------


def test_the_adapter_reports_guesses_a_log_and_a_score(baseline):
    estimate = baseline.estimate(LEAKY)
    assert estimate.guesses > 0
    assert estimate.log10_guesses == pytest.approx(
        __import__("math").log10(estimate.guesses), abs=1e-6
    )
    assert 0 <= estimate.score <= 4


def test_the_adapter_names_itself_and_its_version(baseline):
    assert baseline.name == "zxcvbn"
    assert baseline.version
    assert baseline.describe() == {"name": "zxcvbn", "version": baseline.version}


def test_pattern_names_cross_the_boundary_but_matched_text_does_not(baseline):
    """zxcvbn's sequence entries carry the matched substring and the wordlist
    entry it matched. Both are pieces of the password."""
    estimate = baseline.estimate(LEAKY)
    assert "dictionary" in estimate.patterns

    text = json.dumps(estimate.to_dict(), ensure_ascii=False)
    assert LEAKY not in text
    assert "sharma" not in text
    assert "2024" not in text


def test_a_random_string_reads_as_bruteforce(baseline):
    assert baseline.estimate("qxzjvwkmrt").patterns == ("bruteforce",)


def test_zxcvbn_already_knows_some_romanized_indic_words(baseline):
    """Recorded as a fact about the baseline, not assumed away.

    zxcvbn's English and name lists are not Indic, but they are not innocent of
    Indic words either. Any benchmark that treated "Indic word" as "invisible
    to zxcvbn" would be measuring its own assumption.
    """
    for word in ("namaste", "bharat", "krishna", "sharma"):
        estimate = baseline.estimate(word)
        assert "dictionary" in estimate.patterns, word


def test_feedback_is_generic_advice_and_never_quotes_the_password(baseline):
    """zxcvbn's feedback is canned advice, but it is carried across verbatim,
    so it is checked rather than assumed."""
    estimate = baseline.estimate("krishna1999")
    assert estimate.feedback
    assert all(isinstance(note, str) for note in estimate.feedback)
    for note in estimate.feedback:
        assert "krishna" not in note.lower()
        assert "1999" not in note
