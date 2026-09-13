"""`python3 -m carla_determinism` -- the preflight and its commands. See cli.py.

A separate __main__ rather than running preflight.py directly: __init__ imports
preflight, so `python3 -m carla_determinism.preflight` re-executes an
already-imported module and Python warns about it.
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
