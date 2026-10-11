"""CuteySnowball package.

A pure-Python Forward/Backward Snowballing tool for Systematic Literature
Reviews (SLR) and Systematic Mapping Studies (SMS).

Public entry point:
    from cutesnowball import create_app
"""

__version__ = "0.8.0"
__author__ = "TadavomnisT"
__license__ = "GPL-3.0-or-later"

from .app import create_app  # noqa: E402,F401
