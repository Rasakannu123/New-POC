"""
Demo entry point.

Runs the LangGraph document-extraction pipeline end to end:
    PDF -> images -> enhance -> assess -> route -> extract -> JSON

Every node prints the feature it is working on to the terminal.

Usage:
    python main.py                    # every PDF in data/input
    python main.py path/to/file.pdf   # one specific PDF
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.pipeline_graph import run

if __name__ == "__main__":
    files = [Path(arg) for arg in sys.argv[1:]] or None
    sys.exit(run(files))
