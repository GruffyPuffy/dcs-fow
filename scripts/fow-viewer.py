#!/usr/bin/env python3
"""Compatibility launcher for the manual FoW server."""

from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("fow-server.py")), run_name="__main__")
