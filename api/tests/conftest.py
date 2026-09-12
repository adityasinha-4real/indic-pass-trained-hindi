"""Makes ``api`` and ``indicpass`` importable when running ``pytest api/tests``
from the project root, without touching the root ``pyproject.toml``'s pytest
configuration (which stays scoped to ``tests/`` -- see api/README.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
