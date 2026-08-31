"""Unicode and writing-system helpers for Indic text.

Transliteration data has one failure mode that matters more than any other:
a pair whose "native" side is not actually written in the script it claims --
Latin left in a Devanagari column, Tamil text filed under Telugu, mojibake from
a bad decode. The ratio helpers here make that measurable rather than a guess.

"Neutral" characters (joiners, digits, punctuation, spaces) are excluded from
every ratio: a correct Kannada word should not be marked down for containing a
ZWJ, and a string of pure punctuation should not be counted as valid script.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # avoid a runtime import cycle
    from indicpass.config import Config, Language

__all__ = [
    "ascii_ratio",
    "collapse_whitespace",
    "detect_language",
    "is_probably_romanized",
    "normalize",
    "script_ratio",
]

# Zero-width joiner / non-joiner: structurally required inside Indic clusters.
_JOINERS = frozenset({0x200C, 0x200D})


def normalize(text: str, form: str = "NFC") -> str:
    """Apply Unicode normalisation, tolerating an unknown/blank *form*.

    NFC is the right default for Indic scripts: it composes canonically so two
    visually identical strings compare equal and deduplicate correctly.
    """
    if not text:
        return ""
    if form and form.upper() in {"NFC", "NFD", "NFKC", "NFKD"}:
        return unicodedata.normalize(form.upper(), text)  # type: ignore[arg-type]
    return text


def collapse_whitespace(text: str) -> str:
    """Trim the ends and squeeze runs of internal whitespace to one space."""
    return " ".join(text.split())


def _is_neutral(
    char: str,
    neutral_codepoints: frozenset[int],
    neutral_categories: frozenset[str],
) -> bool:
    if ord(char) in neutral_codepoints or ord(char) in _JOINERS:
        return True
    return unicodedata.category(char) in neutral_categories


def script_ratio(
    text: str,
    ranges: Sequence[tuple[int, int]],
    *,
    neutral_codepoints: frozenset[int] = frozenset(),
    neutral_categories: frozenset[str] = frozenset(),
) -> float:
    """Fraction of *significant* characters in *text* that fall inside *ranges*.

    Returns ``0.0`` for empty text or text made entirely of neutral characters,
    so "no evidence" never reads as "perfectly valid".
    """
    significant = 0
    inside = 0
    for char in text:
        if _is_neutral(char, neutral_codepoints, neutral_categories):
            continue
        significant += 1
        point = ord(char)
        if any(start <= point <= end for start, end in ranges):
            inside += 1

    return inside / significant if significant else 0.0


def ascii_ratio(text: str) -> float:
    """Fraction of significant characters that are ASCII letters.

    Digits, punctuation and whitespace are ignored, so ``"ok-2"`` scores 1.0.
    """
    significant = 0
    latin = 0
    for char in text:
        if char.isspace() or unicodedata.category(char).startswith(("P", "N", "S")):
            continue
        significant += 1
        if "a" <= char.lower() <= "z":
            latin += 1
    return latin / significant if significant else 0.0


def is_probably_romanized(text: str, threshold: float = 0.9) -> bool:
    """True when *text* looks like Roman-script input (Hinglish, Tanglish, ...)."""
    return ascii_ratio(text) >= threshold


def language_script_ratio(text: str, language: "Language", config: "Config") -> float:
    """Convenience wrapper: how much of *text* is in *language*'s script."""
    return script_ratio(
        text,
        language.unicode_ranges,
        neutral_codepoints=config.neutral_codepoints,
        neutral_categories=config.neutral_categories,
    )


def detect_language(
    text: str,
    config: "Config",
    *,
    candidates: Iterable["Language"] | None = None,
    threshold: float = 0.5,
) -> "Language | None":
    """Guess which configured language's script *text* is written in.

    Returns the best-scoring language above *threshold*, or ``None`` when the
    text is Romanized, empty or ambiguous. Purely script-based -- it cannot
    tell apart languages that share a script (Hindi vs. Marathi), which is why
    the pipeline trusts the dataset's own language label over this function.
    """
    pool = list(candidates) if candidates is not None else list(config.languages.values())
    best: Language | None = None
    best_score = 0.0

    for language in pool:
        score = language_script_ratio(text, language, config)
        if score > best_score:
            best, best_score = language, score

    return best if best_score >= threshold else None
