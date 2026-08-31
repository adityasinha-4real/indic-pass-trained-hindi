"""IndicPass -- multilingual Indian transliteration and code-mixed text processing.

Two groups of modules, split by what they need installed:

Pure Python -- run on ``requirements/base.txt`` alone:
    config, logging_utils, cli, records, script_utils, hub,
    tokenizer, metrics
    (``seeding`` too: it imports torch inside its functions, not at module
    level, so it can be imported anywhere.)

Need ``requirements/ml.txt`` (torch) to import at all:
    data, model, trainer

Nothing is imported eagerly here, so ``import indicpass`` stays cheap and
works on a machine that has never installed torch. Import the submodule you
need.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
