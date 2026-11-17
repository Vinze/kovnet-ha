"""Load api.py on its own: it only needs aiohttp, not Home Assistant."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

API_PATH = Path(__file__).parent.parent / "custom_components" / "kovnet" / "api.py"

spec = importlib.util.spec_from_file_location("kovnet_api", API_PATH)
kovnet_api = importlib.util.module_from_spec(spec)
sys.modules["kovnet_api"] = kovnet_api
spec.loader.exec_module(kovnet_api)
