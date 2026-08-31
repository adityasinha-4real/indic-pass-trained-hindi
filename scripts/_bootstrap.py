"""Make ``src/`` importable when a script is run straight from the repository.

Importing this module is a no-op once IndicPass is installed with
``pip install -e .``; it only patches ``sys.path`` when it has to. Every script
in this directory imports it before importing ``indicpass``, which is why
``python scripts/<name>.py`` works from the project root with no setup step.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"

if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
