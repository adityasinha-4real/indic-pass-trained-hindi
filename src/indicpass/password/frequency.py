"""Where a word's frequency comes from, and what it is allowed to mean.

Milestone 1 shipped without frequency because Aksharantar has none: its only
numeric column is a mining log-likelihood present on one subsource, and the
subsource named ``AK-Freq`` is not frequency-ordered. Rather than invent a
number, every entry carried ``frequency: None`` and the guess model fell back
to a word's provenance tier. That fallback prices ``bharat`` -- one of the most
common words in Hindi -- at 42,904 guesses, which is wrong by two orders of
magnitude and is exactly the kind of error a benchmark would then attribute to
"Indic awareness".

This module supplies the missing quantity from an external, versioned corpus:
``wordfreq``.

What the number is
------------------
``wordfreq.zipf_frequency(word, "hi")`` is ``log10`` of the word's occurrences
per **billion** tokens, over Hindi Wikipedia, OSCAR web text, Twitter and
Reddit. It is a *corpus word frequency* and nothing else. It is not a password
frequency, not a model score, and not a measure of how likely someone is to
choose the word -- those are stated as limitations in
``docs/password_strength_design.md`` rather than papered over here.

The join is through the native script
-------------------------------------
wordfreq is keyed on Devanagari; IndicDict is keyed on Roman spellings. The
bridge is the native form the transliterator produced at build time, with the
corpus's own attested forms as a second chance when the model's output is
unknown to the table. Which of the two produced the hit is recorded on the
entry, so a reader can tell a model-mediated frequency from a corpus-mediated
one instead of having to trust the pipeline.

Coverage is partial and that is reported, not hidden
----------------------------------------------------
The shipped Hindi list holds ~27k words, against IndicDict's ~298k spellings.
Roughly one entry in seven gets an observed frequency, and the *rate* is itself
informative: it is far higher for human-written romanizations than for
model-mined ones. Entries with no observed frequency keep ``frequency: None``
and are priced by the documented tier fallback -- never by a substituted
"average" value, which would be fabrication with extra steps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "FrequencyLookup",
    "FrequencyReading",
    "FrequencySource",
    "load_frequency_lookup",
]


class FrequencyUnavailable(RuntimeError):
    """Raised when a configured frequency provider cannot be loaded."""


@dataclass(frozen=True)
class FrequencySource:
    """Provenance for a frequency table. Written into every artefact it touches.

    The point of carrying this around rather than a bare float is that a
    frequency is only interpretable next to its source: "5.1" means nothing
    without "Zipf, wordfreq 3.1.1, Hindi small list".
    """

    #: Provider package, e.g. ``"wordfreq"``.
    provider: str
    version: str
    #: Provider's own language code (``"hi"``), which is not IndicPass's
    #: (``"hin"``) -- keeping both visible prevents a silent mis-join.
    language: str
    wordlist: str
    #: What a value *is*. Copied verbatim into reports.
    semantics: str
    #: Number of words in the table.
    entries: int
    license: str
    #: Corpora the provider aggregated for this language.
    corpora: tuple[str, ...] = ()
    notes: str = ""

    @property
    def identifier(self) -> str:
        return f"{self.provider}-{self.version}/{self.language}/{self.wordlist}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "provider": self.provider,
            "version": self.version,
            "language": self.language,
            "wordlist": self.wordlist,
            "semantics": self.semantics,
            "entries": self.entries,
            "license": self.license,
            "corpora": list(self.corpora),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class FrequencyReading:
    """The outcome of one lookup: a value, or an explicit absence.

    ``value is None`` means *not observed*. It never means zero, and no caller
    may treat it as a number -- which is why the absence is a distinct object
    rather than a sentinel float.
    """

    value: float | None
    #: ``"native_form"`` (the model's prediction was in the table),
    #: ``"attested_form"`` (a corpus-attested spelling was), or ``None``.
    matched_via: str | None = None
    source: FrequencySource | None = None

    @property
    def observed(self) -> bool:
        return self.value is not None


#: A reading that found nothing. Shared because it is by far the common case.
NOT_OBSERVED = FrequencyReading(value=None)


@dataclass
class FrequencyLookup:
    """A frequency table plus the provenance needed to interpret it."""

    source: FrequencySource
    table: Mapping[str, float]
    #: Try the corpus's attested native forms when the model's prediction is
    #: unknown to the table. Off makes the join strictly model-mediated.
    use_attested_forms: bool = True
    _misses: int = field(default=0, repr=False)

    def __len__(self) -> int:
        return len(self.table)

    def lookup(self, native_form: str, attested_forms: Sequence[str] = ()) -> FrequencyReading:
        """Frequency for a dictionary entry, or an explicit "not observed".

        The model's own prediction is tried first: it is what the entry claims
        the word is. Attested forms are a fallback for the case where the
        transliterator produced a spelling the frequency table does not know --
        a real and common outcome at CER 0.108.
        """
        value = self.table.get(native_form)
        if value is not None:
            return FrequencyReading(value=value, matched_via="native_form", source=self.source)

        if self.use_attested_forms:
            # Best available, not first: several attested spellings can be in
            # the table and the attacker reaches the word by its commonest one.
            best: float | None = None
            for form in attested_forms:
                candidate = self.table.get(form)
                if candidate is not None and (best is None or candidate > best):
                    best = candidate
            if best is not None:
                return FrequencyReading(
                    value=best, matched_via="attested_form", source=self.source
                )

        self._misses += 1
        return NOT_OBSERVED


def load_frequency_lookup(
    language: str,
    *,
    provider: str = "wordfreq",
    wordlist: str = "small",
    use_attested_forms: bool = True,
) -> FrequencyLookup:
    """Build a lookup for *language* (the provider's own code, e.g. ``"hi"``).

    Raises rather than degrading silently: a build that was configured to use
    frequency and quietly produced a frequency-free dictionary would be
    indistinguishable from the Milestone 1 artefact, and every guess estimate
    would change without the report saying so.
    """
    if provider != "wordfreq":
        raise FrequencyUnavailable(
            f"Unknown frequency provider {provider!r}. Only 'wordfreq' is implemented; "
            "see docs/password_strength_design.md for the sources that were considered."
        )

    try:
        import wordfreq
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise FrequencyUnavailable(
            "The 'wordfreq' package is not installed, so no frequency source is available.\n"
            "    python -m pip install -r requirements/base.txt\n"
            "Or set frequency.enabled: false in config/password.yaml to build the "
            "tier-only dictionary (and say so in any report)."
        ) from exc

    import importlib.metadata as metadata

    if language not in wordfreq.available_languages(wordlist):
        available = sorted(wordfreq.available_languages(wordlist))
        raise FrequencyUnavailable(
            f"wordfreq has no {wordlist!r} list for {language!r}. Available: {available}"
        )

    table = wordfreq.get_frequency_dict(language, wordlist=wordlist)
    # Zipf, not the raw per-token probability: it is the scale wordfreq itself
    # documents, it is linear in log space, and it keeps the numbers in an
    # inspectable 0-8 range instead of 1e-9.
    zipf = {word: _zipf(value) for word, value in table.items()}

    return FrequencyLookup(
        source=FrequencySource(
            provider="wordfreq",
            version=metadata.version("wordfreq"),
            language=language,
            wordlist=wordlist,
            semantics=(
                "Zipf frequency: log10(occurrences per billion tokens) of the "
                "NATIVE-SCRIPT word in a general text corpus. A corpus word "
                "frequency -- not a password frequency and not a model score."
            ),
            entries=len(zipf),
            license="Apache-2.0 (package); aggregated corpora under their own terms",
            corpora=("Wikipedia", "OSCAR web text", "Twitter", "Reddit"),
            notes=(
                "wordfreq 3.x is a frozen dataset: its author stopped updating it in "
                "2024, which makes it reproducible but means it reflects pre-2022 "
                "text. Only a 'small' list ships for Hindi (~27k words)."
            ),
        ),
        table=zipf,
        use_attested_forms=use_attested_forms,
    )


def _zipf(frequency: float) -> float:
    """wordfreq's own conversion from per-token probability to the Zipf scale."""
    import math

    return round(math.log10(frequency) + 9, 2)
