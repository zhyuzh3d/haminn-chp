"""``python -m hamdraw_chp [serve]`` — the package's second entry point.

    python -m hamdraw_chp serve

A passthrough, and that is the whole design.  ``hamdraw_chp/__init__.py`` is the
*plugin* entry: ComfyUI imports it and the routes go onto ComfyUI's own server.
Python imports that package before it runs this file, so by the time we get a line
of our own, the in-process backend is already bound — which is exactly why the
mode is switched in :func:`hamdraw_chp.cli.main` (the first thing the launcher
does) instead of being guessed from an environment variable or from ``sys.argv``
here.  Mode is decided by who started the process; this file only knows how to
start it.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
