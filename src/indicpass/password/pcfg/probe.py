"""Targeted cases and the random control, for reading the PCFG rather than scoring it.

The 1,400-sample benchmark says whether the model moved. It does not say *why*,
and a per-category mean cannot show that ``bharat2024`` parsed as word+year while
``bharatXqz9`` fell back to the character model. These probes exist to make the
derivations legible one at a time.

Two rules carry over from Milestone 2 unchanged.

**The probe set is a measuring instrument, not a target.** Cases were chosen to
cover the structures the grammar claims to model, including the ones it is
expected to handle badly. Nothing was chosen because it produced a good number,
and no dictionary entry was added to make one of these parse.

**Nothing composed reaches disk.** A probe password is still password material.
The report writes ``case_id``, ``family`` and the note -- never the string --
which is the same rule the benchmark corpus follows. The strings are committed
*source*, here, where a reader can see the whole instrument at once; what the
rule forbids is a published table that pairs an identifier with a password, and
:func:`describe_case` cannot produce one.
"""

from __future__ import annotations

import math
import random
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from indicpass.password.benchmark import ENGLISH_WORDS, INDIC_WORDS
from indicpass.password.pcfg.estimator import PcfgEstimator
from indicpass.password.pcfg.grammar import CATEGORY_WORD

__all__ = [
    "RANDOM_CONTROL_ALPHABETS",
    "RANDOM_CONTROL_LENGTHS",
    "TARGETED_CASES",
    "TargetedCase",
    "character_model_fit",
    "describe_case",
    "random_control_probe",
    "score_targeted_cases",
]


@dataclass(frozen=True)
class TargetedCase:
    """One hand-chosen password and the behaviour it is meant to expose."""

    case_id: str
    family: str
    password: str
    #: What this case is testing, in a sentence. Published; the password is not.
    note: str

    def label(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "length": len(self.password),
            "note": self.note,
        }


#: The nine families the milestone brief names, plus the coverage cases that
#: separate "the grammar works" from "the dictionary happens to contain it".
#: Words marked *absent* are absent from Aksharantar's Hindi split at source --
#: see ``docs/password_strength_design.md`` §12 -- and are the reason the
#: character model exists.
TARGETED_CASES: tuple[TargetedCase, ...] = (
    # -- single Indic word ------------------------------------------------
    TargetedCase(
        "single-01", "single_indic_word", "bharat",
        "A common Hindi word, present in the dictionary with a measured rank.",
    ),
    TargetedCase(
        "single-02", "single_indic_word", "krishna",
        "A named entity, present, priced by measured rank.",
    ),
    TargetedCase(
        "single-03", "single_indic_word", "namaste",
        "Absent from the corpus. Only the character model can explain it.",
    ),
    TargetedCase(
        "single-04", "single_indic_word", "sharma",
        "A very common surname, absent from the corpus. The coverage ceiling.",
    ),
    # -- word + year ------------------------------------------------------
    TargetedCase(
        "year-01", "indic_word_year", "bharat2024",
        "The canonical structure: a dictionary word and a recent year.",
    ),
    TargetedCase(
        "year-02", "indic_word_year", "krishna1998",
        "A named entity and a birth year.",
    ),
    TargetedCase(
        "year-03", "indic_word_year", "namaste2020",
        "The same structure with the word absent from the dictionary.",
    ),
    # -- word + number ----------------------------------------------------
    TargetedCase(
        "digits-01", "indic_word_digits", "bharat123",
        "A digit run that is not a year, so the year terminal must not fire.",
    ),
    TargetedCase(
        "digits-02", "indic_word_digits", "krishna786",
        "A culturally common three-digit suffix. The grammar has no special case for it.",
    ),
    TargetedCase(
        "digits-03", "indic_word_digits", "bharat49281",
        "A five-digit run: the length prior's cost should dominate the word's.",
    ),
    # -- multiple Indic words ---------------------------------------------
    TargetedCase(
        "multi-01", "multiple_indic_words", "merabharat",
        "Two of the commonest words in Hindi, concatenated.",
    ),
    TargetedCase(
        "multi-02", "multiple_indic_words", "bharatmata",
        "A set phrase, as two dictionary lookups.",
    ),
    TargetedCase(
        "multi-03", "multiple_indic_words", "merapyaarbharat",
        "Three segments: the structure prior charges for the extra split.",
    ),
    # -- Indic + English --------------------------------------------------
    TargetedCase(
        "mixed-01", "indic_and_english", "bharatpassword",
        "An Indic word and the commonest English password word.",
    ),
    TargetedCase(
        "mixed-02", "indic_and_english", "welcomebharat",
        "The same pair in the other order.",
    ),
    TargetedCase(
        "mixed-03", "indic_and_english", "krishnadragon",
        "A named entity and an English wordlist staple.",
    ),
    # -- Indic + symbols --------------------------------------------------
    TargetedCase(
        "symbol-01", "indic_and_symbols", "bharat@2024",
        "Word, symbol, year: three segments, the shape a password policy produces.",
    ),
    TargetedCase(
        "symbol-02", "indic_and_symbols", "krishna!",
        "A single trailing symbol, the cheapest possible symbol run.",
    ),
    TargetedCase(
        "symbol-03", "indic_and_symbols", "mera#$%bharat",
        "A three-character symbol run between two words.",
    ),
    # -- case variation ---------------------------------------------------
    TargetedCase(
        "case-01", "case_variation", "Bharat",
        "Capitalised. Must cost about twice the lower-case form, not orders more.",
    ),
    TargetedCase(
        "case-02", "case_variation", "BHARAT",
        "All upper case: the same two variations as capitalised.",
    ),
    TargetedCase(
        "case-03", "case_variation", "BhArAt",
        "Genuinely mixed case, where the variation count really does grow.",
    ),
    TargetedCase(
        "case-04", "case_variation", "Bharat2024",
        "Case variation inside a multi-segment structure.",
    ),
    # -- unseen token -----------------------------------------------------
    TargetedCase(
        "unseen-01", "unseen_token", "bhagwaan",
        "Hindi-shaped and absent: the case the character model exists for.",
    ),
    TargetedCase(
        "unseen-02", "unseen_token", "chhotabhai",
        "Two Hindi-shaped pieces, at least one unseen.",
    ),
    TargetedCase(
        "unseen-03", "unseen_token", "qwxzjvkp",
        "Roman letters with no Hindi shape at all. Must NOT look like a word.",
    ),
    TargetedCase(
        "unseen-04", "unseen_token", "namaste123",
        "An unseen word with digits -- the Milestone 1 fragment pathology's home.",
    ),
    # -- random -----------------------------------------------------------
    TargetedCase(
        "random-01", "random_string", "kqzjxwvbnr",
        "Ten lower-case letters, no structure. The control the model must not flatter.",
    ),
    TargetedCase(
        "random-02", "random_string", "7Kq2xZ9mLp",
        "Mixed alphanumeric, ten characters.",
    ),
    TargetedCase(
        "random-03", "random_string", "x9#Lq2@vZ7!m",
        "Full charset, twelve characters.",
    ),
)


def describe_case(
    case: TargetedCase, estimate: Any, *, baseline: Any = None, reference: Any = None
) -> dict[str, Any]:
    """A publishable row: identity, structure and numbers. Never the password."""
    payload: dict[str, Any] = {
        **case.label(),
        "pcfg": {
            "log10_guesses": round(estimate.log10_guesses, 4),
            "score": estimate.score,
            "log10_probability": round(estimate.log10_probability, 4),
            "grammar_log10_guesses": round(estimate.grammar_log10_guesses, 4),
            "bruteforce_log10_guesses": round(estimate.bruteforce_log10_guesses, 4),
            "floor_applied": estimate.floor_applied,
            "structure": list(estimate.structure),
            "segments": [
                {
                    "category": segment["category"],
                    "length": segment["length"],
                    "log10_probability": segment["log10_probability"],
                    "observed_frequency": segment.get("observed_frequency"),
                    "tier": segment.get("tier"),
                    "rank": segment.get("rank"),
                }
                for segment in estimate.segments
            ],
        },
    }
    if reference is not None:
        payload["indicpass"] = {
            "log10_guesses": round(reference.log10_guesses, 4),
            "score": reference.strength_score,
            "patterns": [m.pattern for m in reference.matched_patterns],
        }
    if baseline is not None:
        payload["zxcvbn"] = {
            "log10_guesses": round(baseline.log10_guesses, 4),
            "score": baseline.score,
            "patterns": list(baseline.patterns),
        }
    if baseline is not None:
        payload["combined_log10_guesses"] = round(
            min(estimate.log10_guesses, baseline.log10_guesses), 4
        )
    return payload


def score_targeted_cases(
    estimator: PcfgEstimator,
    *,
    meter: Any = None,
    baseline: Any = None,
    cases: Sequence[TargetedCase] = TARGETED_CASES,
) -> list[dict[str, Any]]:
    """Score every targeted case with whichever estimators were supplied."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(
            describe_case(
                case,
                estimator.estimate(case.password),
                baseline=baseline.estimate(case.password) if baseline else None,
                reference=meter.score(case.password) if meter else None,
            )
        )
    return rows


# -- what the character model actually learned -----------------------------


def character_model_fit(
    estimator: PcfgEstimator, *, seed: int = 42, samples: int = 500, length: int = 10
) -> dict[str, Any]:
    """The n-gram's cost per character on four populations it never chose.

    This is the single most explanatory measurement in the milestone, and it
    answers two different questions at once.

    **Did the character model generalise, or memorise?** Compare the cost on
    bank words the dictionary *contains* -- which the model trained on -- with
    the cost on bank words the dictionary is *missing*, which it has never seen.
    If those two numbers match, the model learned the shape of Romanized Hindi
    rather than a list of spellings, and that is precisely the capability
    Milestone 2's coverage ceiling called for.

    **Can it beat the brute-force floor?** The floor charges
    ``log10(cardinality)`` per character. Whatever the model's discrimination
    between Hindi and noise, only the margin over *that* can ever reach a
    reported estimate -- and the margin, not the discrimination, is what decides
    whether the character model changes an answer.

    Costs are reported as ``-log10 P`` per character, so **lower means the model
    finds the text likelier**, and the numbers are directly comparable with the
    floor.
    """
    grammar = estimator.grammar
    ngram = grammar.ngram
    rng = random.Random(f"character-model-fit:{seed}")
    alphabet = string.ascii_lowercase

    present = [word for word in INDIC_WORDS if word in grammar.dictionary.entries]
    absent = [word for word in INDIC_WORDS if word not in grammar.dictionary.entries]
    english = [word.lower() for word in ENGLISH_WORDS]
    random_strings = [
        "".join(rng.choice(alphabet) for _ in range(length)) for _ in range(samples)
    ]

    populations = {
        "indic_bank_in_dictionary": present,
        "indic_bank_absent_from_dictionary": absent,
        "english_control": english,
        "random_lowercase": random_strings,
    }
    return {
        "seed": seed,
        "ngram_order": grammar.settings.ngram_order,
        "populations": {
            name: {
                "words": len(words),
                "log10_cost_per_character": round(-ngram.log10_probability_per_character(words), 4),
            }
            for name, words in populations.items()
        },
        # Read from the estimator's own settings, so this row cannot drift away
        # from the floor that actually decides the reported number.
        "bruteforce_floor_cost_per_character": round(
            math.log10(estimator.settings.cardinality_for("a" * length)), 4
        ),
        "bruteforce_floor_applied": estimator.settings.bruteforce_floor,
        "note": (
            "Cost is -log10 P per character; lower means the model finds the text "
            "likelier. The dictionary-present and dictionary-absent rows are the "
            "generalisation test: if they match, the model learned the shape of the "
            "language rather than its vocabulary. The floor row is the bar any of it "
            "has to clear before it can change a reported estimate."
        ),
    }


# -- the random control ----------------------------------------------------

#: Bracket real password lengths. Lower-case is the only alphabet a
#: Romanized-Indic grammar could plausibly hallucinate a word inside, so it is
#: the cell that matters and it is swept at every length.
RANDOM_CONTROL_LENGTHS: tuple[int, ...] = (6, 8, 10, 12, 14)
RANDOM_CONTROL_ALPHABETS: dict[str, str] = {
    "lower": string.ascii_lowercase,
    "alnum": string.ascii_letters + string.digits,
    "full": string.ascii_letters + string.digits + "@!#$*&_.-+",
}


def random_control_probe(
    estimator: PcfgEstimator,
    *,
    seed: int,
    samples: int = 300,
    lengths: Sequence[int] = RANDOM_CONTROL_LENGTHS,
    alphabets: Mapping[str, str] | None = None,
    baseline: Any = None,
) -> dict[str, Any]:
    """Does the PCFG invent lexical structure in strings that have none?

    This is the control that decides whether any Indic result is believable. A
    grammar that also lowered random strings would be finding structure that is
    not there, and the Indic effect would be an artefact of the same mechanism.

    Three numbers per cell:

    ``word_rate``
        Share of random strings whose winning derivation contains a ``word``
        segment. The direct measure of hallucinated lexical structure.

    ``below_bruteforce_rate``
        Share where the grammar alone priced the string *below* enumerating it.
        This is the one that would matter for an estimate: the floor hides a
        word-category hit that was more expensive than brute force anyway.

    ``mean_grammar_minus_bruteforce``
        How far above brute force the grammar sits, in log10. Positive means the
        grammar finds random strings *harder* than enumeration does, which is
        what a well-behaved model should say about them.

    Deterministic in *seed*, seeded per cell from a string so that adding a
    length or an alphabet leaves every other cell's strings untouched.
    """
    table = dict(alphabets or RANDOM_CONTROL_ALPHABETS)
    rows: list[dict[str, Any]] = []

    for name, alphabet in table.items():
        for length in lengths:
            rng = random.Random(f"pcfg-random-control:{seed}:{name}:{length}")
            words = 0
            below = 0
            gaps: list[float] = []
            differences: list[float] = []

            for _ in range(samples):
                password = "".join(rng.choice(alphabet) for _ in range(length))
                estimate = estimator.estimate(password)
                if any(category == CATEGORY_WORD for category in estimate.structure):
                    words += 1
                if estimate.grammar_log10_guesses < estimate.bruteforce_log10_guesses:
                    below += 1
                gaps.append(
                    estimate.grammar_log10_guesses - estimate.bruteforce_log10_guesses
                )
                if baseline is not None:
                    differences.append(
                        estimate.log10_guesses
                        - baseline.estimate(password).log10_guesses
                    )

            row: dict[str, Any] = {
                "alphabet": name,
                "length": length,
                "samples": samples,
                "word_rate": round(words / samples, 4),
                "below_bruteforce_rate": round(below / samples, 4),
                "mean_grammar_minus_bruteforce": round(sum(gaps) / samples, 4),
            }
            if differences:
                row["mean_vs_baseline"] = round(sum(differences) / samples, 4)
            rows.append(row)

    return {
        "seed": seed,
        "samples_per_cell": samples,
        "rows": rows,
        "worst_word_rate": max((row["word_rate"] for row in rows), default=0.0),
        "worst_below_bruteforce_rate": max(
            (row["below_bruteforce_rate"] for row in rows), default=0.0
        ),
        "note": (
            "word_rate is how often the winning derivation contains a dictionary "
            "segment; below_bruteforce_rate is how often the grammar alone priced a "
            "random string below enumerating it. The second is the one that could "
            "change an estimate. A model that read random strings as cheaper than "
            "brute force would be inventing structure, and every Indic result would "
            "have to be read as the same artefact."
        ),
    }
