"""pytest bootstrap used only during the Docker build's map-building run.
It loads tools/map_plugin.py so the audit hooks (module loads + open() events)
record which tests touch which parts of the codebase.

At run time the conftest is harmless: it is not part of the /data run.
"""
import os

_plugin = os.environ.get("BR_MAP_PLUGIN")
if _plugin:
    import sys
    sys.path.insert(0, os.path.dirname(_plugin))
    import map_plugin  # noqa: F401
