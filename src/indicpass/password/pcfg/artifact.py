"""The committed PCFG artefact: what is stored, and what is deliberately not.

``data/pcfg/pcfg_<lang>.json`` holds the guess curve, every hyper-parameter, and
the provenance needed to prove the curve belongs to the dictionary it is used
with. It does **not** hold the grammar's parameters, for two separate reasons.

**The word distribution would be redundant.** Every probability it assigns is a
function of the dictionary's own ``frequency`` and ``tier`` fields, so storing
it would mean committing a second copy of 297,747 numbers that can drift from
the first. The grammar is refitted at load time instead, and a **fingerprint**
over ``(spelling, frequency, tier)`` proves the refit is against the same data
the curve was built from. A mismatch is an error, not a warning: a curve built
for one lexicon and applied to another is a silently wrong number.

**The n-gram would be large and is cheap.** Around 14,000 contexts at order 4,
refitted in a couple of seconds from the same dictionary. Committing it would
add megabytes to the repository for no reproducibility gain the fingerprint does
not already provide.

What remains is small, human-readable, diffable, and holds no password: the
sampler that produced the curve discarded every string it drew.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from indicpass.password.dictionary import IndicDict
from indicpass.password.pcfg.estimator import (
    EstimatorSettings,
    GuessCurve,
    PcfgEstimator,
)
from indicpass.password.pcfg.grammar import GrammarSettings, PcfgGrammar
from indicpass.password.scoring import StrengthScale

__all__ = [
    "ARTIFACT_VERSION",
    "PcfgArtifactError",
    "dictionary_fingerprint",
    "load_estimator",
    "save_estimator",
]

#: Bump when the artefact's schema changes. A reader refuses a version it does
#: not know rather than guessing at a missing field.
ARTIFACT_VERSION = "1.0"


class PcfgArtifactError(RuntimeError):
    """Raised when an artefact is missing, unreadable, or does not match its dictionary."""


def dictionary_fingerprint(dictionary: IndicDict) -> str:
    """A stable digest of everything the grammar is fitted from.

    Deliberately over ``(spelling, frequency, tier)`` rather than over the file:
    that is exactly the projection the grammar reads, so an ablation that drops
    a tier gets a different fingerprint (it must -- it is a different grammar),
    while a rebuild that only changes a comment or a timestamp does not.
    """
    digest = hashlib.sha256()
    for key in sorted(dictionary.entries):
        entry = dictionary.entries[key]
        frequency = "" if entry.frequency is None else f"{entry.frequency:.6f}"
        digest.update(f"{key}\t{frequency}\t{entry.tier}\n".encode())
    digest.update(f"entries={len(dictionary.entries)}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def save_estimator(
    estimator: PcfgEstimator,
    path: Path,
    *,
    language: str,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write the artefact. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    dictionary = estimator.grammar.dictionary
    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "language": language,
        "estimator_version": estimator.version,
        "grammar": estimator.grammar.settings.to_dict(),
        "estimator": estimator.settings.to_dict(),
        "training": {
            "dictionary": {
                "entries": len(dictionary),
                "ranked_entries": dictionary.ranked_total,
                "frequency_coverage": round(dictionary.frequency_coverage, 6),
                "frequency_source": dictionary.frequency_source,
                "fingerprint": dictionary_fingerprint(dictionary),
                "built_at": dictionary.metadata.get("built_at"),
                "model": (dictionary.metadata.get("model") or {}).get("identifier"),
            },
            "ngram": estimator.grammar.ngram.describe(),
            "word_distribution": estimator.grammar.words.to_dict(),
        },
        "curve": estimator.curve.to_dict(),
        "contents_note": (
            "Holds the guess curve and hyper-parameters only. The grammar is refitted "
            "from the dictionary named by the fingerprint above; nothing here is a "
            "password, and the sampler that produced the curve never assembled one."
        ),
        **dict(metadata or {}),
    }

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_estimator(
    path: Path,
    *,
    dictionary: IndicDict,
    scale: StrengthScale,
    scoring: Mapping[str, Any],
    verify_fingerprint: bool = True,
) -> PcfgEstimator:
    """Refit the grammar from *dictionary* and attach the stored curve.

    *scoring* supplies the brute-force floor's settings, which live in the
    shared ``scoring`` block so that the floor cannot drift away from the one
    the Milestone 2 estimator uses -- comparing two estimators that disagree
    about brute force would repeat the mistake Milestone 2 measured and fixed.
    """
    path = Path(path)
    if not path.is_file():
        raise PcfgArtifactError(
            f"No PCFG artefact at {path}.\nTrain one with:\n"
            f"    python scripts/train_pcfg.py --languages {dictionary.language}"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PcfgArtifactError(f"{path} is not valid JSON: {exc}") from exc

    version = str(payload.get("artifact_version", ""))
    if version != ARTIFACT_VERSION:
        raise PcfgArtifactError(
            f"{path} is artefact version {version!r}; this build reads "
            f"{ARTIFACT_VERSION!r}. Retrain it."
        )

    stored = str((payload.get("training") or {}).get("dictionary", {}).get("fingerprint", ""))
    if verify_fingerprint:
        actual = dictionary_fingerprint(dictionary)
        if stored != actual:
            raise PcfgArtifactError(
                f"{path} was trained against a different dictionary.\n"
                f"  artefact:   {stored}\n"
                f"  dictionary: {actual}\n"
                "The guess curve is only valid for the lexicon it was sampled from. "
                f"Retrain with:\n    python scripts/train_pcfg.py "
                f"--languages {dictionary.language}"
            )

    grammar_settings = GrammarSettings.from_config(
        {"grammar": payload.get("grammar") or {}}, scoring
    )
    estimator_settings = EstimatorSettings.from_config(
        {"estimator": payload.get("estimator") or {}}, scoring
    )

    grammar = PcfgGrammar.train(dictionary, grammar_settings)
    curve = GuessCurve.from_dict(payload["curve"])

    return PcfgEstimator(
        grammar,
        curve,
        settings=estimator_settings,
        scale=scale,
        version=str(payload.get("estimator_version", "1.0")),
        provenance={
            "artifact": {
                "path": path.name,
                "artifact_version": version,
                "language": payload.get("language"),
                "generated_at": payload.get("generated_at"),
                "git_commit": payload.get("git_commit"),
                "dictionary_fingerprint": stored,
                "frequency_source": (
                    (payload.get("training") or {})
                    .get("dictionary", {})
                    .get("frequency_source")
                ),
            }
        },
    )
