from __future__ import annotations

import sys
from pathlib import Path

RETRIEVAL_SOURCE = (
    Path(__file__).resolve().parents[3] / "packages" / "retrieval" / "src"
)
sys.path.insert(0, str(RETRIEVAL_SOURCE))
