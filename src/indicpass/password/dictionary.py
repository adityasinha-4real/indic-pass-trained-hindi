"""IndicDict: the Romanized-Indic wordlist the meter looks passwords up in.

Built offline by ``scripts/build_indicdict.py`` and read here. The trained
transliterator is a *dictionary-construction asset*: it runs once, at build
time, and never at scoring time. That separation is why scoring a password
costs a dict lookup instead of a neural forward pass, and why a benchmark run
is reproducible from a committed file rather than from a model's mood.

How an entry is priced
----------------------
The guess model needs one number per word: **how far down an attacker's
wordlist it sits**. Two policies produce that number, and every entry records
which one it used, because they are not equally trustworthy.

``observed_rank``
    The word's native form was found in an external frequency table
    (:mod:`indicpass.password.frequency`). All such entries are sorted by
    descending corpus frequency and numbered ``1 .. R``. An attacker with a
    frequency-ordered wordlist reaches the word at about that position. This is
    real evidence: ``bharat`` lands near the top because भारत genuinely is one
    of the commonest words in Hindi.

``tier_fallback``
    No frequency was observed. The word is priced by its **provenance tier** --
    how the pair was produced -- using only the tier's size and its position in
    the ordering, never a within-tier rank, because the data justifies no
    within-tier ordering. All fallback entries sit *after* the ranked band: an
    attacker with frequency data exhausts the words they can order before
    reaching the ones they cannot.

The fallback is a stated policy, not a substituted value. ``frequency`` and
``rank`` stay ``None`` on those entries; they are never filled in with a tier
average, and :meth:`IndicDict.guess_position` returns the policy alongside the
number so a caller can report how much of a result rests on each.

Aksharantar itself still supplies no frequency
----------------------------------------------
The corpus's one numeric field (``score``) exists only on the model-mined
IndicCorp subsource and is a mining log-likelihood in [-0.35, 0]; the subsource
named ``AK-Freq`` is not frequency-ordered (its first entries are words like
*maitrologist*). Neither is reinterpreted as frequency anywhere. What frequency
exists here came from outside, and says so in ``frequency_source``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = [
    "DictionaryError",
    "GuessPosition",
    "IndicDict",
    "IndicDictEntry",
    "Tier",
]

#: The two pricing policies. Anything reading ``GuessPosition.policy`` should
#: compare against these rather than against string literals of its own.
OBSERVED_RANK = "observed_rank"
TIER_FALLBACK = "tier_fallback"


class DictionaryError(RuntimeError):
    """Raised when a dictionary file is missing or malformed."""


@dataclass(frozen=True)
class GuessPosition:
    """Where in an attacker's wordlist an entry sits, and how we know."""

    position: float
    #: :data:`OBSERVED_RANK` or :data:`TIER_FALLBACK`.
    policy: str
    #: The tier's name when the fallback was used, else ``None``.
    tier: str | None = None


@dataclass(frozen=True)
class Tier:
    """One provenance band within the dictionary.

    A tier holds every entry produced that way (``size``), but only the
    ``unranked_size`` of them that got no observed frequency are *priced* by the
    tier: the rest have a rank of their own and do not need one. ``offset`` is
    therefore how many entries an attacker exhausts before reaching this tier's
    fallback band -- the whole ranked band, plus the fallback bands of every
    better tier.
    """

    name: str
    index: int
    #: Every entry filed under this tier, ranked or not.
    size: int
    #: Entries with an observed frequency rank.
    ranked_size: int
    #: Entries priced by this tier's fallback.
    unranked_size: int
    offset: int

    @property
    def expected_position(self) -> float:
        """Expected guesses to reach an arbitrary *unranked* word in this tier.

        Within the fallback band the order is unknown, so a uniform draw is the
        honest model: the expected position of a uniformly random item among
        *unranked_size* is ``(unranked_size + 1) / 2``, on top of everything
        already exhausted.
        """
        return self.offset + (self.unranked_size + 1) / 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "size": self.size,
            "ranked_size": self.ranked_size,
            "unranked_size": self.unranked_size,
            "offset": self.offset,
        }


@dataclass(frozen=True)
class IndicDictEntry:
    """One Romanized Indic word an attacker could plausibly have in a wordlist."""

    romanized_form: str
    native_form: str
    language: str
    tier: str
    #: Aksharantar subsource the pair came from (Dakshina, Wikidata, ...).
    source: str
    #: Native forms actually attested for this spelling in the corpus.
    attested_forms: tuple[str, ...] = ()
    #: True when the transliterator's output is among the attested forms.
    model_verified: bool = False
    #: Distinct native forms attested for this spelling. A real count from the
    #: corpus -- NOT a frequency, and not used in scoring.
    variant_count: int = 0

    # -- the four quantities that must never be collapsed into one ----------
    #: Corpus word frequency of the NATIVE form, on the provider's scale.
    #: ``None`` means not observed; it never means zero.
    frequency: float | None = None
    #: 1-based position in the descending-frequency ordering of this
    #: dictionary. Computed by :meth:`IndicDict.from_entries`, not stored
    #: authoritatively, so a subset of the dictionary re-ranks consistently.
    rank: int | None = None
    #: Which table the frequency came from, e.g. ``"wordfreq-3.1.1/hi/small"``.
    frequency_source: str | None = None
    #: ``"native_form"`` or ``"attested_form"`` -- which spelling matched.
    frequency_matched_via: str | None = None
    #: Reserved and deliberately unpopulated. The transliterator is decoded
    #: greedily with no calibrated probability, so there is no confidence score
    #: to record; ``model_verified`` is the real, observed agreement signal.
    #: Kept as a distinct field so nothing is tempted to read the mining score
    #: or a tier position as though it were confidence.
    model_confidence: float | None = None

    @property
    def has_frequency(self) -> bool:
        return self.frequency is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "romanized_form": self.romanized_form,
            "native_form": self.native_form,
            "language": self.language,
            "tier": self.tier,
            "source": self.source,
            "attested_forms": list(self.attested_forms),
            "model_verified": self.model_verified,
            "model_confidence": self.model_confidence,
            "variant_count": self.variant_count,
            "frequency": self.frequency,
            "rank": self.rank,
            "frequency_source": self.frequency_source,
            "frequency_matched_via": self.frequency_matched_via,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IndicDictEntry:
        return cls(
            romanized_form=str(data["romanized_form"]),
            native_form=str(data.get("native_form", "")),
            language=str(data.get("language", "")),
            tier=str(data.get("tier", "")),
            source=str(data.get("source", "")),
            attested_forms=tuple(data.get("attested_forms") or ()),
            model_verified=bool(data.get("model_verified", False)),
            variant_count=int(data.get("variant_count", 0)),
            frequency=data.get("frequency"),
            rank=data.get("rank"),
            frequency_source=data.get("frequency_source"),
            frequency_matched_via=data.get("frequency_matched_via"),
            model_confidence=data.get("model_confidence"),
        )


@dataclass
class IndicDict:
    """A loaded dictionary: spelling -> entry, plus the pricing structure.

    Lookups are exact and case-sensitive on the *already normalised* key. The
    matcher lowercases before asking, and records the case transformation it
    had to undo separately -- keeping the two apart is what stops "NAMASTE"
    from being scored as an unknown string.
    """

    language: str
    entries: dict[str, IndicDictEntry] = field(default_factory=dict)
    tiers: dict[str, Tier] = field(default_factory=dict)
    #: How many entries carry an observed frequency rank.
    ranked_total: int = 0
    #: Provenance of the frequency table, when one was used.
    frequency_source: dict[str, Any] | None = None
    #: Build provenance, when a ``.meta.json`` sidecar was found.
    metadata: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, word: object) -> bool:
        return word in self.entries

    def get(self, word: str) -> IndicDictEntry | None:
        return self.entries.get(word)

    def tier_of(self, entry: IndicDictEntry) -> Tier:
        tier = self.tiers.get(entry.tier)
        if tier is None:
            raise DictionaryError(
                f"Entry {entry.romanized_form!r} claims tier {entry.tier!r}, which is not "
                f"one of {sorted(self.tiers)}. Rebuild the dictionary against the current "
                "config/password.yaml."
            )
        return tier

    def guess_position(self, entry: IndicDictEntry) -> GuessPosition:
        """How far down an attacker's wordlist *entry* sits, and by which policy.

        This is the single place the two pricing policies meet, so a caller
        cannot accidentally use one while reporting the other.
        """
        if entry.rank is not None:
            return GuessPosition(position=float(entry.rank), policy=OBSERVED_RANK)
        tier = self.tier_of(entry)
        return GuessPosition(
            position=tier.expected_position, policy=TIER_FALLBACK, tier=tier.name
        )

    @property
    def total_entries(self) -> int:
        return sum(tier.size for tier in self.tiers.values())

    @property
    def frequency_coverage(self) -> float:
        """Fraction of entries priced by an observed rank rather than a tier."""
        return self.ranked_total / len(self.entries) if self.entries else 0.0

    # -- construction ------------------------------------------------------

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[IndicDictEntry],
        *,
        language: str,
        tier_order: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
        frequency_source: Mapping[str, Any] | None = None,
    ) -> IndicDict:
        """Index *entries*, rank the ones with a frequency, and size the tiers.

        Ranks are **recomputed here** rather than trusted from the file. An
        ablation that loads a subset -- the mined tier dropped, say -- must
        re-rank against the entries it actually holds, or every guess estimate
        in that run would refer to a wordlist that was not used.

        *tier_order* comes from ``config/password.yaml`` and fixes the fallback
        offsets. Reordering it changes every unranked estimate, which is why it
        is configuration and not a property of the file.
        """
        indexed: dict[str, IndicDictEntry] = {}

        for entry in entries:
            if entry.tier not in tier_order:
                raise DictionaryError(
                    f"Entry {entry.romanized_form!r} has tier {entry.tier!r}, not in the "
                    f"configured tier order {list(tier_order)}."
                )
            # A spelling in several tiers belongs to the best one: that is the
            # cheapest place an attacker finds it, and guessing is a minimum.
            existing = indexed.get(entry.romanized_form)
            if existing is not None and tier_order.index(existing.tier) <= tier_order.index(
                entry.tier
            ):
                continue
            indexed[entry.romanized_form] = entry

        ranked_total = _assign_ranks(indexed)

        counts = dict.fromkeys(tier_order, 0)
        unranked = dict.fromkeys(tier_order, 0)
        for entry in indexed.values():
            counts[entry.tier] += 1
            if entry.rank is None:
                unranked[entry.tier] += 1

        tiers: dict[str, Tier] = {}
        # The fallback band starts where the ranked band ends: an attacker
        # holding frequency data works through everything they can order first.
        offset = ranked_total
        for index, name in enumerate(tier_order):
            tiers[name] = Tier(
                name=name,
                index=index,
                size=counts[name],
                ranked_size=counts[name] - unranked[name],
                unranked_size=unranked[name],
                offset=offset,
            )
            offset += unranked[name]

        return cls(
            language=language,
            entries=indexed,
            tiers=tiers,
            ranked_total=ranked_total,
            frequency_source=dict(frequency_source) if frequency_source else None,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def load(cls, path: Path, *, language: str, tier_order: Sequence[str]) -> IndicDict:
        """Read a JSONL dictionary, plus its ``.meta.json`` sidecar if present."""
        path = Path(path)
        if not path.is_file():
            raise DictionaryError(
                f"No IndicDict at {path}.\nBuild one with:\n"
                f"    python scripts/build_indicdict.py --languages {language}"
            )

        metadata: dict[str, Any] = {}
        sidecar = path.with_suffix(".meta.json")
        if sidecar.is_file():
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))

        return cls.from_entries(
            _read_entries(path),
            language=language,
            tier_order=tier_order,
            metadata=metadata,
            frequency_source=metadata.get("frequency_source"),
        )

    def save(self, path: Path, *, metadata: Mapping[str, Any] | None = None) -> Path:
        """Write the dictionary as JSONL, ordered by tier then spelling.

        Deterministic ordering keeps the committed file's diff readable when it
        is rebuilt, and makes the build itself verifiable by re-running it.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        ordered = sorted(
            self.entries.values(),
            key=lambda entry: (self.tiers[entry.tier].index, entry.romanized_form),
        )
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for entry in ordered:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False))
                handle.write("\n")

        payload = {
            "language": self.language,
            "entries": len(self.entries),
            "tiers": [
                tier.to_dict() for tier in sorted(self.tiers.values(), key=lambda t: t.index)
            ],
            "frequency_available": self.ranked_total > 0,
            "ranked_entries": self.ranked_total,
            "frequency_coverage": round(self.frequency_coverage, 6),
            "frequency_source": self.frequency_source,
            "frequency_note": (
                "Frequency is a corpus word frequency of the NATIVE form, taken from an "
                "external table; Aksharantar itself supplies none. Entries with no "
                "observed frequency keep frequency: null and rank: null and are priced "
                "by the documented tier fallback -- no value is substituted for them."
            ),
            **dict(metadata or {}),
        }
        path.with_suffix(".meta.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.metadata = payload
        return path


def _assign_ranks(indexed: dict[str, IndicDictEntry]) -> int:
    """Number the entries that have a frequency, commonest first. Returns how many.

    Entries without one have their ``rank`` cleared, so a stale rank read from
    a file can never survive into a dictionary whose frequency table is gone.

    Ties are broken by ``(length, spelling)``. Frequencies are shared whenever
    two romanizations map to the same native word, so ties are common and the
    ordering has to be total or the file would not round-trip.
    """
    with_frequency = [
        entry for entry in indexed.values() if entry.frequency is not None
    ]
    with_frequency.sort(
        key=lambda e: (-float(e.frequency or 0.0), len(e.romanized_form), e.romanized_form)
    )

    for position, entry in enumerate(with_frequency, start=1):
        indexed[entry.romanized_form] = replace(entry, rank=position)
    for key, entry in indexed.items():
        if entry.frequency is None and entry.rank is not None:
            indexed[key] = replace(entry, rank=None)

    return len(with_frequency)


def _read_entries(path: Path) -> Iterator[IndicDictEntry]:
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield IndicDictEntry.from_dict(json.loads(text))
            except (json.JSONDecodeError, KeyError) as exc:
                raise DictionaryError(f"{path}:{number} is not a valid entry: {exc}") from exc
