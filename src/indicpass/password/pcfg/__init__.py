"""An Indic-aware probabilistic context-free grammar over passwords.

Milestone 2 produced an *estimator*: a wordlist position, a handful of
multipliers, and a combinatorial rule borrowed from zxcvbn. It worked, and its
own documentation was clear that most of it was heuristic. This package replaces
the guess formula with a **probability model** and derives the guess number from
it, which is a different kind of object and buys three things the estimator
could not have.

1. **The pieces are normalised.** ``P(word)``, ``P(case | word)``, ``P(k)`` --
   each is a distribution that sums to one, so they compose. Milestone 2's
   "position x variations x penalty" was a product of numbers that were not
   probabilities and could not be reasoned about jointly.

2. **Guess numbers come from counting, not from a formula.** ``G(x)`` is
   estimated as the number of passwords the model ranks at or above *x*, by
   Monte-Carlo sampling from the grammar itself. No ``k!``, no ``D^(k-1)``,
   no wordlist index standing in for a rank.

3. **Words the dictionary never saw are still modelled.** A character n-gram
   trained on the 297,747 Romanized spellings recognises the *shape* of Hindi,
   so ``namaste`` -- absent from Aksharantar at source, and Milestone 2's single
   largest limitation -- is no longer indistinguishable from a random string.

What it does not buy is accuracy. Nothing here has been validated against an
observed cracking attack, so "the PCFG estimates fewer guesses" remains a
statement about two models. The structure prior in particular is **not learned**:
learning it needs a password corpus, this repository has none, and fitting it to
the synthetic benchmark would measure the generator. It is an explicit
maximum-entropy prior, and the reports say how much the conclusion depends on it.

Modules
-------
``ngram``      the character model over Romanized spellings, Witten-Bell smoothed
``grammar``    nonterminals, priors, terminal distributions, and sampling
``parser``     the maximum-probability derivation of one password
``estimator``  probability to guess number, and the strength score
``artifact``   the committed JSON artefact and its dictionary fingerprint
``probe``      targeted cases and the random control

The design, with every choice labelled measured / heuristic / assumption, is
``docs/password_strength_design.md`` §14.
"""

from __future__ import annotations

from indicpass.password.pcfg.artifact import (
    ARTIFACT_VERSION,
    PcfgArtifactError,
    dictionary_fingerprint,
    load_estimator,
    save_estimator,
)
from indicpass.password.pcfg.estimator import (
    EstimatorSettings,
    GuessCurve,
    PcfgEstimate,
    PcfgEstimator,
)
from indicpass.password.pcfg.grammar import (
    PCFG_CATEGORIES,
    CaseModel,
    GrammarSettings,
    PcfgGrammar,
    WordDistribution,
)
from indicpass.password.pcfg.ngram import CharacterNgram
from indicpass.password.pcfg.parser import Derivation, PcfgSegment, best_derivation
from indicpass.password.pcfg.probe import (
    TARGETED_CASES,
    TargetedCase,
    random_control_probe,
    score_targeted_cases,
)

__all__ = [
    "ARTIFACT_VERSION",
    "PCFG_CATEGORIES",
    "TARGETED_CASES",
    "CaseModel",
    "CharacterNgram",
    "Derivation",
    "EstimatorSettings",
    "GrammarSettings",
    "GuessCurve",
    "PcfgArtifactError",
    "PcfgEstimate",
    "PcfgEstimator",
    "PcfgGrammar",
    "PcfgSegment",
    "TargetedCase",
    "WordDistribution",
    "best_derivation",
    "dictionary_fingerprint",
    "load_estimator",
    "random_control_probe",
    "save_estimator",
    "score_targeted_cases",
]
