"""The IndicPass meter: password in, :class:`PasswordStrengthResult` out.

This is the only object most callers need. It wires the configured dictionaries
into a matcher, runs the optimal-segmentation search, and turns the winning
segmentation into a guess number, a 0-4 score and some plain-language warnings.

No neural model is loaded and none is invoked. The transliterator's entire
contribution arrived earlier, offline, as the IndicDict file this reads --
which is what makes scoring a dictionary lookup rather than a forward pass, and
what makes a benchmark run reproducible from committed artefacts.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from indicpass.config import Config, load_config
from indicpass.password.baseline import PasswordStrengthBaseline, load_baseline
from indicpass.password.dictionary import TIER_FALLBACK, IndicDict
from indicpass.password.matcher import MatcherSettings, PasswordMatcher
from indicpass.password.pcfg.artifact import load_estimator
from indicpass.password.pcfg.estimator import PcfgEstimator
from indicpass.password.result import Match, PasswordStrengthResult, guesses_from_log10
from indicpass.password.scoring import ScoringSettings, StrengthScale, best_segmentation

__all__ = ["IndicPassMeter", "describe_dictionaries", "describe_pcfg"]


class IndicPassMeter:
    """Estimates how many guesses a password costs an attacker.

    A *baseline* may be attached. When one is, every result carries the generic
    estimator's verdict on the same password alongside IndicPass's own, which
    is the only form in which the two are allowed to be compared: same
    password, same call, no re-derivation later from a report.

    A *PCFG* may be attached the same way, and for the same reason. It is a
    third opinion on the same password in the same call -- **not** a
    replacement for this meter's own number. ``score()`` still returns the
    Milestone 2 estimate in ``guess_number``; the grammar's estimate lives in
    ``result.pcfg``. Swapping the primary estimator is a conclusion the
    comparison has to reach, not a side effect of adding a model to the object.
    """

    def __init__(
        self,
        dictionaries: Sequence[IndicDict],
        *,
        matcher_settings: MatcherSettings,
        scoring_settings: ScoringSettings,
        scale: StrengthScale,
        named_entity_tiers: Sequence[str] = (),
        baseline: PasswordStrengthBaseline | None = None,
        pcfg: PcfgEstimator | None = None,
    ) -> None:
        self.dictionaries = list(dictionaries)
        self.scoring_settings = scoring_settings
        self.scale = scale
        self.named_entity_tiers = frozenset(named_entity_tiers)
        self.baseline = baseline
        self.pcfg = pcfg
        self.matcher = PasswordMatcher(
            self.dictionaries, matcher_settings, named_entity_tiers=self.named_entity_tiers
        )

    # -- construction ------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: Config | None = None,
        *,
        languages: Sequence[str] | None = None,
        dictionary_paths: Sequence[Path] | None = None,
        with_baseline: bool | None = None,
        with_pcfg: bool | None = None,
    ) -> IndicPassMeter:
        """Build a meter from ``config/password.yaml``.

        *dictionary_paths* overrides the configured files, which is what the
        tests use to score against a small fixture instead of the real 300k
        entry dictionary. *with_baseline* overrides ``baseline.enabled``, and
        *with_pcfg* overrides ``pcfg.enabled``.
        """
        config = config or load_config()
        strength = config.password_section("strength")
        dictionary_config = config.password_section("dictionary")
        matching = config.password_section("matching")
        scoring = config.password_section("scoring")
        baseline_config = config.password_section("baseline")
        pcfg_config = config.password_section("pcfg")

        tiers = list(dictionary_config.get("tiers") or [])
        tier_order = [str(tier["name"]) for tier in tiers]
        named = [str(tier["name"]) for tier in tiers if tier.get("named_entity")]

        wanted = list(languages) if languages else list(dictionary_config.get("files") or {})
        loaded: list[IndicDict] = []
        if dictionary_paths is not None:
            for code, path in zip(wanted, dictionary_paths, strict=True):
                loaded.append(IndicDict.load(Path(path), language=code, tier_order=tier_order))
        else:
            files = dictionary_config.get("files") or {}
            for code in wanted:
                if code not in files:
                    raise KeyError(
                        f"config/password.yaml lists no dictionary for {code!r}. "
                        f"Configured: {sorted(files)}"
                    )
                loaded.append(
                    IndicDict.load(
                        config.resolve(files[code]), language=code, tier_order=tier_order
                    )
                )

        enabled = (
            bool(baseline_config.get("enabled", False))
            if with_baseline is None
            else with_baseline
        )
        baseline = (
            load_baseline(str(baseline_config.get("implementation", "zxcvbn")))
            if enabled
            else None
        )

        scale = StrengthScale.from_config(strength)
        want_pcfg = (
            bool(pcfg_config.get("enabled", False)) if with_pcfg is None else with_pcfg
        )
        pcfg = None
        if want_pcfg and loaded:
            # One grammar per meter, over the first dictionary. The PCFG is a
            # single-language model by construction -- its character n-gram and
            # its word distribution are both fitted to one lexicon -- so
            # attaching it to a multi-language meter would silently score Hindi
            # spellings against a Hindi grammar and everything else against the
            # same one. Milestone 3 is Hindi only, and this says so.
            artifacts = pcfg_config.get("files") or {}
            code = loaded[0].language
            if code not in artifacts:
                raise KeyError(
                    f"config/password.yaml lists no PCFG artefact for {code!r}. "
                    f"Configured: {sorted(artifacts)}. Train one with "
                    f"scripts/train_pcfg.py, or set pcfg.enabled: false."
                )
            pcfg = load_estimator(
                config.resolve(artifacts[code]),
                dictionary=loaded[0],
                scale=scale,
                scoring=scoring,
            )

        return cls(
            loaded,
            matcher_settings=MatcherSettings.from_config(matching, scoring),
            scoring_settings=ScoringSettings.from_config(scoring, matching),
            scale=scale,
            named_entity_tiers=named,
            baseline=baseline,
            pcfg=pcfg,
        )

    # -- scoring -----------------------------------------------------------

    def score(self, password: str) -> PasswordStrengthResult:
        """Estimate the guess number for *password* and derive its 0-4 score.

        *password* is read, never stored: what comes back holds its length and
        a description of its structure. See :mod:`indicpass.password.result`.
        """
        matches = self.matcher.matches(password)
        segmentation = best_segmentation(password, matches, self.scoring_settings)

        log10 = segmentation.log10_guesses
        score = self.scale.score(log10)
        winning = segmentation.matches

        indic = tuple(m.token for m in winning if m.pattern == "indic_word")
        names = tuple(
            m.token
            for m in winning
            if m.pattern == "indic_word" and m.detail.get("is_named_entity")
        )
        variants = tuple(
            dict.fromkeys(
                str(m.detail["case_transformation"])
                for m in winning
                if m.pattern == "indic_word"
                and m.detail.get("case_transformation") != "lowercase"
            )
        )

        return PasswordStrengthResult(
            password_length=len(password),
            guess_number=guesses_from_log10(log10),
            log10_guesses=log10,
            strength_score=score,
            strength_label=self.scale.label(score),
            matched_patterns=winning,
            matched_indic_words=indic,
            matched_names=names,
            matched_variants=variants,
            # Redacted by construction: describe() without the token yields
            # pattern, position and cost, never the characters.
            estimated_components=tuple(m.describe() for m in winning),
            warnings=self._warnings(password, winning),
            baseline=self.baseline.estimate(password) if self.baseline else None,
            baseline_name=self.baseline.name if self.baseline else "baseline",
            # include_tokens stays at its default: the segments that reach a
            # result are already redacted, so no serialisation path can leak a
            # piece of the password through the grammar's parse.
            pcfg=self.pcfg.estimate(password) if self.pcfg else None,
        )

    # -- advice ------------------------------------------------------------

    def _warnings(self, password: str, matches: Sequence[Match]) -> tuple[str, ...]:
        """Plain-language observations. Never quotes the password back."""
        notes: list[str] = []
        patterns = [match.pattern for match in matches]

        for match in matches:
            if match.pattern != "indic_word":
                continue
            kind = "name" if match.detail.get("is_named_entity") else "word"
            notes.append(
                f"Contains a {match.detail.get('language', 'Indic')} dictionary {kind} "
                f"({match.length} characters) that a Romanized-Indic wordlist would cover."
            )

        # Say when the number rests on a fallback rather than on evidence. A
        # tier-priced word has no observed frequency, so its position in the
        # attacker's wordlist is a policy, not a measurement -- and that is
        # precisely where this estimate is least trustworthy.
        fallbacks = sum(
            1
            for m in matches
            if m.pattern == "indic_word" and m.detail.get("rank_policy") == TIER_FALLBACK
        )
        if fallbacks:
            notes.append(
                f"{fallbacks} dictionary hit(s) had no observed corpus frequency, so their "
                "cost comes from a provenance-tier fallback rather than a measured rank."
            )

        trailing = [
            m
            for m in matches
            if m.pattern in {"digits", "year"} and m.end == len(password)
        ]
        for match in trailing:
            if match.pattern == "year":
                notes.append("Ends in a year, which is far cheaper to guess than four digits.")
            else:
                notes.append(
                    f"Ends in a {match.length}-digit suffix, a pattern attackers try first."
                )

        if "repeat" in patterns:
            notes.append("Contains a run of repeated characters, which adds little.")

        if any(
            m.pattern == "indic_word" and m.detail.get("case_transformation") != "lowercase"
            for m in matches
        ):
            notes.append(
                "Capitalisation on a dictionary word roughly doubles the work, not more."
            )

        if all(pattern == "bruteforce" for pattern in patterns):
            notes.append(
                "No known word or pattern was recognised; the estimate rests on length "
                "and character variety alone."
            )

        return tuple(notes)

    def __repr__(self) -> str:  # pragma: no cover - display only
        sizes = ", ".join(f"{d.language}={len(d):,}" for d in self.dictionaries)
        return f"<IndicPassMeter dictionaries=[{sizes}]>"


def describe_dictionaries(meter: IndicPassMeter) -> list[dict[str, Any]]:
    """Provenance for a report header: which dictionaries a run actually used."""
    return [
        {
            "language": dictionary.language,
            "entries": len(dictionary),
            "tiers": [
                tier.to_dict()
                for tier in sorted(dictionary.tiers.values(), key=lambda t: t.index)
            ],
            "frequency_available": dictionary.ranked_total > 0,
            "ranked_entries": dictionary.ranked_total,
            "frequency_coverage": round(dictionary.frequency_coverage, 6),
            "frequency_source": dictionary.frequency_source,
            "built_at": dictionary.metadata.get("built_at"),
            "git_commit": dictionary.metadata.get("git_commit"),
        }
        for dictionary in meter.dictionaries
    ]


def describe_pcfg(meter: IndicPassMeter) -> dict[str, Any] | None:
    """Provenance for a report header: which grammar, if any, a run used.

    ``None`` rather than an empty dict when no grammar is attached, so a report
    template cannot render a PCFG section that describes nothing.
    """
    return meter.pcfg.describe() if meter.pcfg else None
