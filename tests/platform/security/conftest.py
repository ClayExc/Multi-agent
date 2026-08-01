from __future__ import annotations

import sys
from pathlib import Path

# Allow sibling platform test modules (factories, conftest) to be imported
# from this security subdirectory without turning tests/platform into a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
