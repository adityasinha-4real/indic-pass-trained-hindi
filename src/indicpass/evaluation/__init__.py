"""A measurement layer over the frozen password-strength research code.

Nothing here is imported by ``indicpass.password.*``, and nothing in this
package computes a guess number, a match, a PCFG probability or an attack
rank -- those are the frozen research artefacts, and this package only reads
their outputs. What lives here is the machinery a rigorous evaluation needs
that the research code had no occasion to build: confusion matrices, ROC/PR
curves, calibration diagnostics, attack-budget success tables and the paired
bootstrap for classification statistics.

Ground truth, throughout this package, means one thing: the position at which
one of the project's two bounded reference attackers
(:mod:`indicpass.password.reference_attack`, Milestone 4; or
:mod:`indicpass.password.character_attack`, Milestone 5) actually reaches a
password. It is never derived from an estimator's own prediction -- see
``docs/evaluation.md`` for the full contract and
``scripts/evaluate_model.py`` for the script that assembles it.
"""

from __future__ import annotations
