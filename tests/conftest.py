"""Shared pytest configuration.

Puts the supercompressible study directory on ``sys.path`` so its
plain-Python modules (``post_processing.py``) are importable from the
test suite; the study is not an installed package.
"""

import sys
from pathlib import Path

STUDY_DIR = (
    Path(__file__).parent.parent
    / "studies"
    / "fragile_becomes_supercompressible"
)
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))
