"""The controlled password set the two estimators are compared on.

The experiment asks one question:

    Does explicit Romanized-Indic lexical modelling reduce estimated guess
    counts for Romanized Indic passwords, relative to a generic estimator?

Answering it needs passwords of known composition, so the corpus is
**generated, not collected**. No real password appears here, and none is read
from anywhere: every sample is assembled from committed word banks by a seeded
generator, which makes a run reproducible from ``evaluation.seed`` alone.

Nothing reaches disk
--------------------
A generated password is still password material -- publishing a list of
"realistic Indic passwords" would be publishing a cracking wordlist. So
:class:`BenchmarkSample` holds its password in memory for the length of a run,
and the reports key their rows on ``sample_id`` and ``category``. Regenerating
the corpus from the same seed reproduces it exactly, which is what
reproducibility actually requires; storing the strings is not.

Stated precisely, because the loose version is false: **no report maps a
sample_id to a password, and no composed password reaches disk** -- nothing of
the form word+digits, word+symbol, word+year, word+word, and no random string.
What can coincide with a report's text is a *single-word* sample, because the
single-word categories are by construction the word banks below, and those are
committed source that the coverage tables print on purpose as the measuring
instrument. Seeing ``bharat`` in a coverage table says nothing about which
sample used it. :func:`BenchmarkSample.label` is what a row may contain.

The word banks are the instrument, not the answer
-------------------------------------------------
The Indic bank is a list of everyday Romanized Hindi -- greetings, kinship
terms, common nouns, the surnames and given names that dominate Indian
passwords. It was written from what a Hindi speaker would plausibly type, and
deliberately **not** drawn from IndicDict: sampling the dictionary would
guarantee coverage and measure nothing. The consequence is that many of these
words are missing from IndicDict, and the benchmark reports that as a result
rather than avoiding it. See ``results/reports/indicdict_coverage_hin.md``.

The English bank plays the reverse role: passwords a generic estimator should
handle well and an Indic lexicon should add nothing to. Note that the two banks
are not cleanly separated in the wild -- ``password`` and ``qwerty`` have
legitimate Devanagari transliterations in Aksharantar, so the Hindi dictionary
covers part of the English control set by accident. That is measured too.
"""

from __future__ import annotations

import random
import string
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CATEGORIES",
    "GENERATOR_VERSION",
    "BenchmarkSample",
    "describe_corpus",
    "generate_corpus",
]

#: Bump when the generator or a word bank changes. A report carries this, so a
#: result can never be silently compared against a corpus it was not run on.
GENERATOR_VERSION = "1.0"

#: The controlled categories. Order fixes each one's seed offset, so adding a
#: category at the end leaves every existing sample unchanged.
CATEGORIES: tuple[str, ...] = (
    "english",
    "indic_word",
    "indic_numeric",
    "indic_year",
    "indic_symbol",
    "mixed",
    "random",
)

#: Everyday Romanized Hindi: greetings, kinship, common nouns and adjectives,
#: then the given names and surnames that dominate real Indian password dumps.
#: Written from usage, NOT sampled from IndicDict -- see the module docstring.
INDIC_WORDS: tuple[str, ...] = (
    # greetings and set phrases
    "namaste", "namaskar", "dhanyavaad", "dhanyavad", "shukriya", "alvida",
    "swagat", "pranam", "salaam", "jaihind", "vandemataram",
    # kinship
    "maa", "papa", "bhai", "behen", "beta", "beti", "dada", "dadi", "nana",
    "nani", "chacha", "chachi", "mama", "mami", "bua", "didi",
    # affection and feeling
    "pyaar", "prem", "ishq", "mohabbat", "dil", "jaan", "yaar", "dost",
    "dosti", "khushi", "gham", "sapna", "umeed", "izzat",
    # everyday nouns
    "ghar", "paani", "khana", "roti", "chai", "doodh", "kitab", "school",
    "gaadi", "paisa", "kaam", "raat", "din", "subah", "shaam", "duniya",
    "zindagi", "raasta", "shahar", "gaon", "desh", "phool", "aasman",
    "chand", "suraj", "samundar", "barish", "hawa", "aag",
    # common adjectives and verbs
    "accha", "bura", "bada", "chota", "sundar", "khushboo", "meetha",
    "garam", "thanda", "jaldi", "dheere", "chalo", "suno", "dekho", "bolo",
    # pronouns and function words people build passwords from
    "mera", "tera", "hamara", "tumhara", "apna", "sabka", "kuch", "bahut",
    # places and nation
    "bharat", "hindustan", "india", "dilli", "mumbai", "kolkata", "chennai",
    "bangalore", "hyderabad", "jaipur", "lucknow", "punjab", "gujarat",
    "kerala", "kashmir", "ganga", "himalaya",
    # given names
    "aditya", "arjun", "rahul", "rohit", "vikram", "amit", "sanjay", "raj",
    "krishna", "shiva", "ganesh", "hanuman", "ram", "sita", "radha", "laxmi",
    "priya", "pooja", "neha", "anjali", "kavita", "sunita", "deepak",
    "manish", "suresh", "ramesh", "ravi", "ajay", "vijay", "anil",
    # surnames
    "sharma", "verma", "gupta", "singh", "kumar", "yadav", "patel", "reddy",
    "nair", "iyer", "chopra", "kapoor", "mehta", "shah", "joshi", "desai",
    "bose", "das", "roy", "mishra", "tiwari", "pandey", "agarwal",
)

#: The generic control: words and passwords a non-Indic estimator should
#: already know. Drawn from the vocabulary that dominates English-language
#: password studies.
ENGLISH_WORDS: tuple[str, ...] = (
    "password", "qwerty", "welcome", "monkey", "dragon", "sunshine",
    "princess", "football", "baseball", "letmein", "master", "shadow",
    "superman", "batman", "trustno", "iloveyou", "starwars", "computer",
    "internet", "michael", "jennifer", "jordan", "hunter", "buster",
    "soccer", "harley", "ranger", "daniel", "hannah", "thomas", "summer",
    "winter", "spring", "autumn", "orange", "purple", "silver", "golden",
    "diamond", "phoenix", "falcon", "eagle", "tiger", "panther", "cobra",
    "matrix", "oracle", "corner", "garden", "window", "morning", "evening",
    "kitchen", "guitar", "camera", "coffee", "chocolate", "birthday",
    "holiday", "freedom", "victory", "mountain", "thunder", "lightning",
    "rainbow", "October", "November", "December", "January", "manager",
    "director", "engineer", "student", "teacher", "doctor", "lawyer",
)

#: Symbols people actually put in passwords, not the full ASCII punctuation
#: set. Skewed towards the shift-number row, which is where they come from.
COMMON_SYMBOLS: tuple[str, ...] = ("@", "!", "#", "$", "*", "&", "_", ".", "-", "+")


@dataclass(frozen=True)
class BenchmarkSample:
    """One generated password and its label.

    ``password`` is deliberately excluded from every serialisation path in this
    package. It exists to be scored and then dropped.
    """

    sample_id: str
    category: str
    password: str
    #: How the sample was assembled, e.g. ``"word+digits"``. Shape only, no
    #: content, so it is safe to publish and useful when reading a report.
    construction: str

    def label(self) -> dict[str, Any]:
        """The publishable part: everything except the password itself."""
        return {
            "sample_id": self.sample_id,
            "category": self.category,
            "construction": self.construction,
            "length": len(self.password),
        }


def _capitalise(rng: random.Random, word: str) -> tuple[str, str]:
    """Apply the case pattern people actually use, or none. Returns the shape too."""
    roll = rng.random()
    if roll < 0.65:
        return word, "lower"
    if roll < 0.90:
        return word.capitalize(), "capitalized"
    return word.upper(), "upper"


def _english(rng: random.Random) -> tuple[str, str]:
    word = rng.choice(ENGLISH_WORDS).lower()
    cased, shape = _capitalise(rng, word)
    if rng.random() < 0.45:
        return f"{cased}{rng.randrange(1, 1000)}", f"english+digits/{shape}"
    return cased, f"english/{shape}"


def _indic_word(rng: random.Random) -> tuple[str, str]:
    cased, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
    return cased, f"indic/{shape}"


def _indic_numeric(rng: random.Random) -> tuple[str, str]:
    cased, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
    digits = rng.choice(("123", "1234", "007", "786", "420", "999", "12345"))
    if rng.random() < 0.25:
        digits = str(rng.randrange(10, 10000))
    return f"{cased}{digits}", f"indic+digits({len(digits)})/{shape}"


def _indic_year(rng: random.Random) -> tuple[str, str]:
    cased, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
    year = rng.randrange(1950, 2026)
    return f"{cased}{year}", f"indic+year/{shape}"


def _indic_symbol(rng: random.Random) -> tuple[str, str]:
    cased, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
    symbol = rng.choice(COMMON_SYMBOLS)
    if rng.random() < 0.55:
        return f"{cased}{symbol}{rng.randrange(1, 1000)}", f"indic+symbol+digits/{shape}"
    return f"{cased}{symbol}", f"indic+symbol/{shape}"


def _mixed(rng: random.Random) -> tuple[str, str]:
    """Two lexical pieces, the combination people reach for when told to be safe."""
    roll = rng.random()
    if roll < 0.4:
        first, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
        second = rng.choice(INDIC_WORDS)
        body, kind = f"{first}{second}", "indic+indic"
    elif roll < 0.75:
        first, shape = _capitalise(rng, rng.choice(INDIC_WORDS))
        second = rng.choice(ENGLISH_WORDS).lower()
        body, kind = f"{first}{second}", "indic+english"
    else:
        first, shape = _capitalise(rng, rng.choice(ENGLISH_WORDS).lower())
        second = rng.choice(INDIC_WORDS)
        body, kind = f"{first}{second}", "english+indic"

    if rng.random() < 0.5:
        symbol = rng.choice(COMMON_SYMBOLS)
        return f"{body}{symbol}{rng.randrange(1, 100)}", f"{kind}+symbol+digits/{shape}"
    if rng.random() < 0.5:
        return f"{body}{rng.randrange(1, 10000)}", f"{kind}+digits/{shape}"
    return body, f"{kind}/{shape}"


def _random(rng: random.Random) -> tuple[str, str]:
    """The upper control: no lexical structure to find, at three charset widths."""
    length = rng.randrange(8, 15)
    roll = rng.random()
    if roll < 0.34:
        alphabet, kind = string.ascii_lowercase, "lower"
    elif roll < 0.67:
        alphabet, kind = string.ascii_letters + string.digits, "alnum"
    else:
        alphabet, kind = string.ascii_letters + string.digits + "".join(COMMON_SYMBOLS), "full"
    return "".join(rng.choice(alphabet) for _ in range(length)), f"random({kind},{length})"


_GENERATORS = {
    "english": _english,
    "indic_word": _indic_word,
    "indic_numeric": _indic_numeric,
    "indic_year": _indic_year,
    "indic_symbol": _indic_symbol,
    "mixed": _mixed,
    "random": _random,
}


def generate_corpus(
    *,
    seed: int,
    samples_per_category: int,
    categories: Sequence[str] = CATEGORIES,
) -> list[BenchmarkSample]:
    """Build the benchmark deterministically from *seed*.

    Each category draws from its own ``Random``, seeded by the corpus seed plus
    the category's fixed index. That makes a category's samples independent of
    how many other categories ran, so an ablation over a subset produces the
    *same* passwords rather than a differently-shuffled set -- without which
    the ablations would not be comparing like with like.

    Duplicates are dropped within a category: with 200 draws from ~180 words,
    the short categories would otherwise repeat samples and quietly weight them
    double in the averages.
    """
    unknown = [name for name in categories if name not in _GENERATORS]
    if unknown:
        raise ValueError(f"Unknown benchmark categories {unknown}. Known: {list(CATEGORIES)}.")

    samples: list[BenchmarkSample] = []
    for category in categories:
        rng = random.Random(seed + CATEGORIES.index(category))
        generate = _GENERATORS[category]
        seen: set[str] = set()
        index = 0
        # Bounded so an over-small word bank cannot spin forever; the shortfall
        # then shows up as a smaller N in the report, which is the honest
        # outcome.
        for _ in range(samples_per_category * 20):
            if len(seen) >= samples_per_category:
                break
            password, construction = generate(rng)
            if password in seen:
                continue
            seen.add(password)
            index += 1
            samples.append(
                BenchmarkSample(
                    sample_id=f"{category}-{index:04d}",
                    category=category,
                    password=password,
                    construction=construction,
                )
            )
    return samples


def describe_corpus(samples: Sequence[BenchmarkSample]) -> dict[str, Any]:
    """Publishable provenance for a benchmark run. Holds no password."""
    counts: dict[str, int] = {}
    lengths: dict[str, list[int]] = {}
    for sample in samples:
        counts[sample.category] = counts.get(sample.category, 0) + 1
        lengths.setdefault(sample.category, []).append(len(sample.password))

    return {
        "generator_version": GENERATOR_VERSION,
        "total_samples": len(samples),
        "categories": {
            name: {
                "samples": counts[name],
                "mean_length": round(sum(lengths[name]) / len(lengths[name]), 2),
                "min_length": min(lengths[name]),
                "max_length": max(lengths[name]),
            }
            for name in counts
        },
        "word_banks": {"indic": len(INDIC_WORDS), "english": len(ENGLISH_WORDS)},
        "note": (
            "Passwords are generated, never stored. Rows are keyed by sample_id; "
            "regenerating from the same seed reproduces the corpus exactly."
        ),
    }


def iter_categories(
    samples: Sequence[BenchmarkSample],
) -> Iterator[tuple[str, list[BenchmarkSample]]]:
    """Group *samples* by category, in :data:`CATEGORIES` order."""
    for category in CATEGORIES:
        group = [sample for sample in samples if sample.category == category]
        if group:
            yield category, group
