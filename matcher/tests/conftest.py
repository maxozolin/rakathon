"""Pytest configuration and shared fixtures.

Ensures avicenna_matcher is importable when running under uv.
"""

import sys
from pathlib import Path

# Add parent directory to sys.path so avicenna_matcher can be imported
matcher_root = Path(__file__).parent.parent
sys.path.insert(0, str(matcher_root))
