"""The standard IndicPass record and JSONL I/O.

Every upstream dataset is flattened into the same shape before anything else
touches it, so downstream code never learns the quirks of a particular source:

    {
      "record_id":      "3f7c1a9e2b4d8c05",   # stable content hash
      "language":       "hin",                 # ISO 639-3
      "script":         "Deva",                # ISO 15924
      "source_text":    "namaste",             # Romanized / code-mixed input
      "target_text":    "नमस्ते",                # native-script output
      "dataset_source": "aksharantar",         # which dataset
      "subsource":      "Dakshina",            # which sub-corpus within it
      "split":          "train"
    }

``record_id`` is a hash of (language, source_text, target_text) only. It is
therefore identical on the development PC and the training PC, survives
re-running the pipeline, and is what both deduplication and hash-based split
assignment key off.

Deliberately, ``subsource`` is *not* part of that hash. Sub-corpus is
provenance, not identity: the same pair mined from two sub-corpora is one pair
and must deduplicate to one record. Adding the field therefore leaves every
previously computed id unchanged.

``subsource`` is optional -- a source that does not distinguish sub-corpora
leaves it empty -- so it is absent from :data:`REQUIRED_FIELDS` and records
written before it existed still validate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

__all__ = [
    "FIELD_ORDER",
    "REQUIRED_FIELDS",
    "SCHEMA_VERSION",
    "Record",
    "assign_split",
    "count_lines",
    "read_jsonl",
    "stable_id",
    "write_jsonl",
]

# 1 -> 2: added the optional `subsource` field. Readers of v1 files are
# unaffected; `subsource` simply reads back as "".
SCHEMA_VERSION = 2

FIELD_ORDER: tuple[str, ...] = (
    "record_id",
    "language",
    "script",
    "source_text",
    "target_text",
    "dataset_source",
    "subsource",
    "split",
)

# Fields that must be present and non-null. `subsource` is excluded: not every
# upstream dataset distinguishes sub-corpora, and v1 files predate the field.
REQUIRED_FIELDS: tuple[str, ...] = tuple(f for f in FIELD_ORDER if f != "subsource")

_ID_LENGTH = 16  # hex chars; 64 bits is ample for tens of millions of records


def stable_id(language: str, source_text: str, target_text: str) -> str:
    """Deterministic content hash for a transliteration pair.

    Uses an explicit separator that cannot occur in the fields, so
    ``("hi", "ab")`` and ``("hia", "b")`` cannot collide.
    """
    payload = "\x1f".join((language, source_text, target_text)).encode("utf-8")
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()[:_ID_LENGTH]


@dataclass(frozen=True, slots=True)
class Record:
    """One standardized transliteration pair."""

    language: str
    script: str
    source_text: str
    target_text: str
    dataset_source: str
    split: str
    #: Sub-corpus within `dataset_source` (Aksharantar: Dakshina, Wikidata,
    #: AK-Freq, ...). Empty when the source does not distinguish one.
    subsource: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not self.record_id:
            # frozen dataclass: bypass the setattr guard to fill the derived id.
            object.__setattr__(
                self,
                "record_id",
                stable_id(self.language, self.source_text, self.target_text),
            )

    @property
    def dedup_key(self) -> tuple[str, str, str]:
        return (self.language, self.source_text, self.target_text)

    def to_dict(self) -> dict[str, Any]:
        """Serialise with a stable key order so output diffs stay readable."""
        raw = asdict(self)
        return {field: raw[field] for field in FIELD_ORDER}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Record":
        """Rebuild a record. Tolerates v1 files, which have no ``subsource``."""
        return cls(
            language=str(data.get("language", "")),
            script=str(data.get("script", "")),
            source_text=str(data.get("source_text", "")),
            target_text=str(data.get("target_text", "")),
            dataset_source=str(data.get("dataset_source", "")),
            subsource=str(data.get("subsource") or ""),
            split=str(data.get("split", "")),
            record_id=str(data.get("record_id", "")),
        )


def assign_split(record_id: str, ratios: Mapping[str, float]) -> str:
    """Deterministically bucket a record into a split from its id.

    Hashing beats shuffling here: the partition depends only on the record's
    content, so it is reproducible across machines, stable when new records are
    appended, and cannot leak through a reordered input file.

    *ratios* need not sum to exactly 1.0; they are normalised.
    """
    if not ratios:
        raise ValueError("assign_split() needs at least one split ratio.")

    total = sum(float(v) for v in ratios.values())
    if total <= 0:
        raise ValueError(f"Split ratios must sum above zero, got {ratios!r}.")

    # 10_000 buckets -> ratios are honoured to within 0.01%.
    bucket = int(record_id[:8], 16) % 10_000
    cumulative = 0.0
    ordered = sorted(ratios.items())
    for name, ratio in ordered:
        cumulative += float(ratio) / total
        if bucket < cumulative * 10_000:
            return name
    return ordered[-1][0]  # float rounding at the very top of the range


def write_jsonl(path: Path, records: Iterable[Record | Mapping[str, Any]]) -> int:
    """Write records as UTF-8 JSON Lines, creating parent directories.

    ``ensure_ascii=False`` keeps native script readable in the file itself,
    which matters a lot when eyeballing Indic data. Returns the count written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            payload = record.to_dict() if isinstance(record, Record) else dict(record)
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
            written += 1
    return written


def read_jsonl(path: Path, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Stream a JSONL file. Malformed lines raise with the line number attached."""
    if not path.is_file():
        raise FileNotFoundError(f"No such JSONL file: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
            if limit is not None and number >= limit:
                return


def read_records(path: Path, *, limit: int | None = None) -> Iterator[Record]:
    """Stream a JSONL file as :class:`Record` objects."""
    for payload in read_jsonl(path, limit=limit):
        yield Record.from_dict(payload)


def count_lines(path: Path) -> int:
    """Count non-empty lines without loading the file into memory."""
    total = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                total += 1
    return total
