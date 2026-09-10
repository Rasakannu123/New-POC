"""
POC entry point.

Runs the full document pipeline end to end:
    Input PDF -> convert -> enhance -> assess -> route -> extract -> Output

All configuration (endpoints, keys, models, paths) is read from .env via
the package config module.
"""

from __future__ import annotations

import sys

from src.doc_extraction.pipeline import run

if __name__ == "__main__":
    sys.exit(run())