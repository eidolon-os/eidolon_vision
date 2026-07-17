"""Make the package importable during tests before an editable install exists."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
