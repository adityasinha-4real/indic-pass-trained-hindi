"""IndicPass password-strength engine.

Estimates how many guesses a password costs an attacker who knows that
Romanized Indic words are password material -- ``namaste``, ``bharat``,
``sharma`` -- and compares that with what a generic estimator would say.

The pieces:

* :mod:`~indicpass.password.dictionary` -- IndicDict, built offline from the
  trained transliterator by ``scripts/build_indicdict.py``.
* :mod:`~indicpass.password.frequency` -- where a word's position in an
  attacker's wordlist comes from, and what it is allowed to mean.
* :mod:`~indicpass.password.matcher` -- finds dictionary and structural
  patterns inside a password, and grades how good each hit is.
* :mod:`~indicpass.password.mangling` -- case transformations and their cost.
* :mod:`~indicpass.password.patterns` -- digits, years, symbols, repeats,
  unexplained spans.
* :mod:`~indicpass.password.scoring` -- picks the attacker's cheapest
  explanation and maps it onto the configured 0-4 scale.
* :mod:`~indicpass.password.pcfg` -- Milestone 3: a probability model over
  passwords, and a guess number derived from it by counting rather than by a
  formula. Runs alongside the estimator above, not instead of it.
* :mod:`~indicpass.password.meter` -- the object that ties those together.
* :mod:`~indicpass.password.baseline` -- the generic estimator (zxcvbn) the
  whole exercise is measured against.
* :mod:`~indicpass.password.benchmark` -- the generated, controlled password
  set the two are compared on.
* :mod:`~indicpass.password.reference_attack` -- Milestone 4: a bounded
  enumeration whose ranks are *observed* rather than estimated, and which
  imports none of the estimators above so that scoring them against it is not
  circular.
* :mod:`~indicpass.password.character_attack` -- Milestone 5: a second such
  attacker, whose candidates come from a character model rather than a wordlist
  so that a spelling missing from IndicDict is reachable too. Milestone 4 could
  not rank one of those, which is the population Milestone 3's character model
  exists for.
* :mod:`~indicpass.password.oov` -- the partition of the benchmark into
  in-lexicon and out-of-lexicon families that Milestone 5's question is asked on.
* :mod:`~indicpass.password.validation` -- the statistics that score an
  estimator against those observed ranks.
* :mod:`~indicpass.password.uncertainty` -- bootstrap confidence intervals for
  those statistics, and the paired intervals on the differences between them.

Nothing here imports torch, and nothing here runs the transliteration model.
The model's contribution is the dictionary file, produced offline.

The design, including the exact formulas, is in
``docs/password_strength_design.md``.
"""

from __future__ import annotations

from indicpass.password.baseline import (
    BaselineEstimate,
    PasswordStrengthBaseline,
    ZxcvbnBaseline,
    load_baseline,
)
from indicpass.password.benchmark import BenchmarkSample, generate_corpus
from indicpass.password.character_attack import (
    CharacterAttack,
    CharacterAttackRank,
    CharacterAttackSettings,
    CharacterModel,
    StemCounter,
)
from indicpass.password.dictionary import GuessPosition, IndicDict, IndicDictEntry, Tier
from indicpass.password.frequency import FrequencyLookup, FrequencySource
from indicpass.password.matcher import MatchClass, MatcherSettings, PasswordMatcher
from indicpass.password.meter import IndicPassMeter
from indicpass.password.oov import OovTargetRow, TargetClass, Taxonomy
from indicpass.password.pcfg import (
    CharacterNgram,
    Derivation,
    GrammarSettings,
    GuessCurve,
    PcfgEstimate,
    PcfgEstimator,
    PcfgGrammar,
)
from indicpass.password.reference_attack import (
    AttackRank,
    AttackSettings,
    Lexicon,
    ReferenceAttack,
)
from indicpass.password.result import Match, PasswordStrengthResult
from indicpass.password.scoring import ScoringSettings, StrengthScale, best_segmentation
from indicpass.password.uncertainty import Interval, bootstrap_group
from indicpass.password.validation import Calibration, MetricSet, ValidationRow

__all__ = [
    "AttackRank",
    "AttackSettings",
    "BaselineEstimate",
    "BenchmarkSample",
    "Calibration",
    "CharacterAttack",
    "CharacterAttackRank",
    "CharacterAttackSettings",
    "CharacterModel",
    "CharacterNgram",
    "Derivation",
    "FrequencyLookup",
    "FrequencySource",
    "GrammarSettings",
    "GuessCurve",
    "GuessPosition",
    "IndicDict",
    "IndicDictEntry",
    "IndicPassMeter",
    "Interval",
    "Lexicon",
    "Match",
    "MatchClass",
    "MatcherSettings",
    "MetricSet",
    "OovTargetRow",
    "PasswordMatcher",
    "PasswordStrengthBaseline",
    "PasswordStrengthResult",
    "PcfgEstimate",
    "PcfgEstimator",
    "PcfgGrammar",
    "ReferenceAttack",
    "ScoringSettings",
    "StemCounter",
    "StrengthScale",
    "TargetClass",
    "Taxonomy",
    "Tier",
    "ValidationRow",
    "ZxcvbnBaseline",
    "best_segmentation",
    "bootstrap_group",
    "generate_corpus",
    "load_baseline",
]
