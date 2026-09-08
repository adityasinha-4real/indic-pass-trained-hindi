"""Partitioning the benchmark by what the dictionary actually contains.

Milestone 3's claim is not about passwords in general. It is about the ones
whose spelling IndicDict never saw -- ``namaste``, ``sharma``, ``ghar`` -- and
scoring it on a population that mixes those with words the dictionary holds
would answer a different question and call it the same one. So the 1,400
benchmark targets are partitioned before any metric is computed, and every
metric is reported per partition as well as overall.

The partition is **mechanical**. Every rule below is a membership test against
the committed dictionary or the committed word bank, applied in a fixed order to
the target's leading run of ASCII letters. No target is placed by hand, no
example is added, and the benchmark is not touched: this module reads the corpus
Milestones 2, 3 and 4 all used and labels it.

The partitions, first match wins
--------------------------------
``random_control``
    The ``random`` benchmark category. The control that decides whether any of
    the rest is believable, and never mixed with a lexical population.

``english_control``
    The ``english`` category. A generic estimator should already handle these,
    so an Indic model should add nothing. Kept separate from the Indic OOV
    families for exactly that reason -- and note some of them ARE in the Hindi
    dictionary, because ``password`` and ``qwerty`` have attested Devanagari
    transliterations. Whether each one is is recorded, not assumed.

``mixed_construction``
    The ``mixed`` category: two lexical pieces concatenated. Its own partition
    because a two-word body is a different object from a word, whether or not
    either half is known.

``indic_in_lexicon``
    An Indic-category body that is a key of IndicDict. The population Milestone
    4 could already reach, and the baseline every OOV number is read against.
    Named apart from the ``in_lexicon`` *group* below, which is plain dictionary
    membership across all seven categories: two populations that would otherwise
    share a name and are not the same set.

``oov_name``
    Absent from the dictionary, and present in the benchmark's own name and
    place bank -- given names, surnames, cities, ``bharat``. Named entities are
    the family that dominates real Indian password dumps and the family a
    transliteration corpus is most likely to be missing, so they are counted
    apart from ordinary vocabulary.

``oov_spelling_variant``
    Absent, but a documented respelling of it is present: ``dhanyavaad`` for
    ``dhanyavad``, ``pyaar`` for ``pyar``. Romanized Hindi has no standard
    orthography, so this is the largest single reason a real spelling misses a
    dictionary built from one corpus.

``oov_morphological_variant``
    Absent, but a prefix of at least four characters is present and at most
    three characters are left over -- a known root carrying an inflection.

``oov_stem_suffix``
    Absent, and contains a known word of at least four characters somewhere
    inside it. A known stem with something longer attached.

``oov_other``
    Absent, and none of the above. Includes anything the four rules above have
    no evidence about.

These labels are a **classification heuristic and not a linguistic claim**. The
morphological and transliteration rules will mislabel some targets in both
directions; what they are for is to keep the OOV population from being reported
as one undifferentiated lump, and the report says so. Nothing in the metric
pipeline depends on getting them right -- the headline OOV set is defined by
plain dictionary membership, which is exact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from indicpass.password.validation import ValidationRow

__all__ = [
    "INDIC_CATEGORIES",
    "NAME_WORDS",
    "OOV_PARTITIONS",
    "PARTITIONS",
    "REPORT_GROUPS",
    "VARIANT_RULES",
    "OovTargetRow",
    "TargetClass",
    "Taxonomy",
    "group_rows",
    "partition_counts",
]

#: In report order. Controls first, then the population Milestone 4 could
#: already reach, then the out-of-lexicon families this milestone exists for.
PARTITIONS: tuple[str, ...] = (
    "random_control",
    "english_control",
    "mixed_construction",
    "indic_in_lexicon",
    "oov_name",
    "oov_spelling_variant",
    "oov_morphological_variant",
    "oov_stem_suffix",
    "oov_other",
)

#: The Indic out-of-lexicon families. Their union, restricted to the four Indic
#: benchmark categories, is the population Milestone 3's claim is about.
OOV_PARTITIONS: tuple[str, ...] = (
    "oov_name",
    "oov_spelling_variant",
    "oov_morphological_variant",
    "oov_stem_suffix",
    "oov_other",
)

#: The benchmark categories built from the Romanized Hindi word bank.
INDIC_CATEGORIES: tuple[str, ...] = (
    "indic_word",
    "indic_numeric",
    "indic_year",
    "indic_symbol",
)

#: The name and place entries of the benchmark's Indic word bank, transcribed
#: from the comment groups in :mod:`indicpass.password.benchmark`: places and
#: nation, given names, surnames. Transcribed rather than sliced by index so a
#: reordering there cannot silently change what counts as a name here -- and
#: ``tests/test_oov.py`` asserts every entry is still in the bank.
NAME_WORDS: frozenset[str] = frozenset(
    {
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
    }
)

#: Respellings tried when deciding whether a missing word is a transliteration
#: variant of one the dictionary holds. Each is applied to every occurrence,
#: producing one variant per rule. They are the substitutions that actually
#: separate two Romanizations of the same Hindi word -- long vowels written
#: doubled or single, and the consonants with no settled Latin spelling.
VARIANT_RULES: tuple[tuple[str, str], ...] = (
    ("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"),
    ("a", "aa"), ("i", "ee"), ("u", "oo"),
    ("v", "w"), ("w", "v"), ("z", "j"), ("j", "z"),
    ("ph", "f"), ("f", "ph"), ("sh", "s"), ("s", "sh"),
    ("kh", "k"), ("th", "t"), ("ch", "c"), ("y", "i"),
)

#: Shortest dictionary hit that counts as evidence of a known stem. Four is the
#: same floor ``matching.min_substring_length`` uses, and for the same measured
#: reason: a three-letter hit occurs in 40% of random strings of that length.
MIN_EVIDENCE_LENGTH = 4

#: Longest leftover that still reads as an inflection rather than a second word.
MAX_INFLECTION_LENGTH = 3


@dataclass(frozen=True)
class TargetClass:
    """One target's partition, and the evidence that put it there.

    Carries no password and no dictionary spelling: lengths and booleans only,
    which is what makes a 1,400-row table publishable.
    """

    partition: str
    in_lexicon: bool
    body_length: int
    #: Longest prefix of the body that is a dictionary key, as a length.
    known_prefix_length: int
    #: The body splits into two dictionary keys -- the two-word reading.
    splits_into_known_words: bool
    #: A dictionary key of at least :data:`MIN_EVIDENCE_LENGTH` occurs inside it.
    contains_known_word: bool
    #: A documented respelling of the body is a dictionary key.
    variant_in_lexicon: bool
    #: The body is in the benchmark's name and place bank.
    is_name: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition": self.partition,
            "in_lexicon": self.in_lexicon,
            "body_length": self.body_length,
            "known_prefix_length": self.known_prefix_length,
            "splits_into_known_words": self.splits_into_known_words,
            "contains_known_word": self.contains_known_word,
            "variant_in_lexicon": self.variant_in_lexicon,
            "is_name": self.is_name,
        }


class Taxonomy:
    """Assigns a partition, given the set of spellings the dictionary holds.

    Built from a plain set of lower-case keys rather than from an ``IndicDict``,
    so the rules can be tested against a ten-word fixture and so this module
    depends on nothing that prices a word.
    """

    def __init__(self, words: Iterable[str], *, names: Iterable[str] = NAME_WORDS) -> None:
        self.words = frozenset(word.lower() for word in words)
        self.names = frozenset(names)
        self._lengths = sorted(
            {len(word) for word in self.words if len(word) >= MIN_EVIDENCE_LENGTH}
        )

    # -- evidence ---------------------------------------------------------

    def body_of(self, password: str) -> str:
        """The leading run of ASCII letters, lower-cased.

        The attack's stem is exactly this run, so classifying on it is
        classifying the thing the attack has to produce. A password with no
        leading letters has an empty body and falls through to the controls.
        """
        head: list[str] = []
        for character in password:
            if not (character.isascii() and character.isalpha()):
                break
            head.append(character)
        return "".join(head).lower()

    def known_prefix_length(self, body: str) -> int:
        for size in range(len(body), MIN_EVIDENCE_LENGTH - 1, -1):
            if body[:size] in self.words:
                return size
        return 0

    def splits_into_known_words(self, body: str) -> bool:
        return any(
            body[:cut] in self.words and body[cut:] in self.words
            for cut in range(MIN_EVIDENCE_LENGTH, len(body) - MIN_EVIDENCE_LENGTH + 1)
        )

    def contains_known_word(self, body: str) -> bool:
        return any(
            body[start : start + size] in self.words
            for size in self._lengths
            if size <= len(body)
            for start in range(len(body) - size + 1)
        )

    def variants(self, body: str) -> list[str]:
        """Documented respellings of *body*, deduplicated and ordered.

        Bounded by construction: one variant per rule plus the all-at-once vowel
        collapse and the dropped final ``a``, so the set is never larger than
        :data:`VARIANT_RULES` plus two.
        """
        seen: dict[str, None] = {}
        for source, target in VARIANT_RULES:
            if source in body:
                seen.setdefault(body.replace(source, target), None)
        collapsed = body
        for source, target in VARIANT_RULES[:5]:
            collapsed = collapsed.replace(source, target)
        seen.setdefault(collapsed, None)
        if body.endswith("a") and len(body) > MIN_EVIDENCE_LENGTH:
            seen.setdefault(body[:-1], None)
        seen.pop(body, None)
        return list(seen)

    # -- the partition -----------------------------------------------------

    def classify(self, password: str, category: str) -> TargetClass:
        """Place one target. First matching rule wins; see the module docstring."""
        body = self.body_of(password)
        in_lexicon = body in self.words
        prefix = self.known_prefix_length(body) if body else 0
        splits = self.splits_into_known_words(body) if body else False
        contains = self.contains_known_word(body) if body else False
        is_name = body in self.names
        variant = (
            any(candidate in self.words for candidate in self.variants(body))
            if body and not in_lexicon
            else False
        )

        if category == "random":
            partition = "random_control"
        elif category == "english":
            partition = "english_control"
        elif category == "mixed":
            partition = "mixed_construction"
        elif in_lexicon:
            partition = "indic_in_lexicon"
        elif is_name:
            partition = "oov_name"
        elif variant:
            partition = "oov_spelling_variant"
        elif prefix >= MIN_EVIDENCE_LENGTH and len(body) - prefix <= MAX_INFLECTION_LENGTH:
            partition = "oov_morphological_variant"
        elif contains:
            partition = "oov_stem_suffix"
        else:
            partition = "oov_other"

        return TargetClass(
            partition=partition,
            in_lexicon=in_lexicon,
            body_length=len(body),
            known_prefix_length=prefix,
            splits_into_known_words=splits,
            contains_known_word=contains,
            variant_in_lexicon=variant,
            is_name=is_name,
        )


# -- rows -------------------------------------------------------------------


@dataclass(frozen=True)
class OovTargetRow:
    """One target: its partition, what the attack did, and what each model said.

    Holds the sample's identity and shape, never its text -- the rule
    :class:`indicpass.password.validation.ValidationRow` enforces, for the same
    reason. ``rank`` is ``None`` exactly when ``reachable`` is false, and
    ``reason`` then names the bound that excluded it.
    """

    sample_id: str
    category: str
    construction: str
    length: int
    classification: TargetClass
    reachable: bool
    rank: int | None
    log10_rank: float | None
    shape: str | None
    level: int | None
    reason: str | None
    predictions: Mapping[str, float] = field(default_factory=dict)

    @property
    def partition(self) -> str:
        return self.classification.partition

    @property
    def in_lexicon(self) -> bool:
        return self.classification.in_lexicon

    def as_validation_row(self) -> ValidationRow:
        """The Milestone 4 statistics take this shape, unchanged.

        Reusing the frozen metric code is deliberate: a second implementation of
        Spearman and MAE would be a second thing to be wrong, and the two
        milestones' tables would stop being comparable the moment they drifted.
        """
        return ValidationRow(
            sample_id=self.sample_id,
            category=self.category,
            construction=self.construction,
            length=self.length,
            covered=self.reachable,
            reference_rank=self.rank,
            log10_reference_rank=self.log10_rank,
            predictions=dict(self.predictions),
            rule=self.shape,
            unseen_stem=not self.in_lexicon,
            case_variant=self.construction.endswith(("/capitalized", "/upper")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "category": self.category,
            "construction": self.construction,
            "length": self.length,
            **self.classification.to_dict(),
            "reachable": self.reachable,
            "attack_rank": self.rank,
            "log10_attack_rank": round(self.log10_rank, 6) if self.log10_rank is not None else None,
            "attack_shape": self.shape,
            "attack_level": self.level,
            "exclusion_reason": self.reason,
            "predictions": {
                name: round(value, 6) for name, value in sorted(self.predictions.items())
            },
        }


#: The populations the report scores separately: four cross-cutting groups, then
#: the nine partitions. Each is a predicate over a row, and they are NOT disjoint
#: -- ``oov`` and ``oov_indic`` overlap the partitions by design. Every table
#: names which one it is showing, because combining incomparable populations
#: without a label is the failure mode this whole milestone is trying to avoid.
#:
#: ``in_lexicon`` here is plain dictionary membership over all seven categories.
#: The partition of nearly the same name is ``indic_in_lexicon`` and is a subset
#: of it; the two are spelled apart so a table can never mean the wrong one.
REPORT_GROUPS: tuple[str, ...] = (
    "all",
    "in_lexicon",
    "oov",
    "oov_indic",
    *PARTITIONS,
)


def group_rows(rows: Sequence[OovTargetRow], group: str) -> list[OovTargetRow]:
    """The rows belonging to one reported population.

    ``in_lexicon`` and ``oov`` are decided by plain dictionary membership, which
    is exact. The partitions are decided by the heuristic rules above. The two
    axes are kept apart on purpose: the headline OOV finding must not depend on
    a classification rule that could be argued with.
    """
    if group == "all":
        return list(rows)
    if group == "in_lexicon":
        return [row for row in rows if row.in_lexicon]
    if group == "oov":
        return [row for row in rows if not row.in_lexicon]
    if group == "oov_indic":
        return [
            row
            for row in rows
            if not row.in_lexicon and row.category in INDIC_CATEGORIES
        ]
    if group in PARTITIONS:
        return [row for row in rows if row.partition == group]
    raise ValueError(f"Unknown reporting group {group!r}. Known: {list(REPORT_GROUPS)}.")


def partition_counts(rows: Sequence[OovTargetRow]) -> dict[str, dict[str, Any]]:
    """Size, dictionary membership and reachability of every partition."""
    summary: dict[str, dict[str, Any]] = {}
    for partition in PARTITIONS:
        selected = [row for row in rows if row.partition == partition]
        reasons: dict[str, int] = {}
        for row in selected:
            if row.reason:
                reasons[row.reason] = reasons.get(row.reason, 0) + 1
        summary[partition] = {
            "targets": len(selected),
            "in_lexicon": sum(1 for row in selected if row.in_lexicon),
            "reachable": sum(1 for row in selected if row.reachable),
            "coverage": (
                round(sum(1 for row in selected if row.reachable) / len(selected), 4)
                if selected
                else 0.0
            ),
            "exclusion_reasons": dict(
                sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
            ),
        }
    return summary
