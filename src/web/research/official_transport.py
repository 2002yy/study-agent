"""Keep Windows system proxies when NO_PROXY is the only environment setting.

CPython's Windows getproxies() returns environment settings *or* registry
settings. A NO_PROXY-only environment therefore hides the actual system proxy.
Do not mutate process environment or override explicit proxy/bypass choices.
"""
from __future__ import annotations

import sys
import urllib.request


_WINDOWS = sys.platform == "win32"


def official_proxy_settings() -> dict[str, str]:
    configured = urllib.request.getproxies()
    if not _WINDOWS or any(key != "no" and value for key, value in configured.items()):
        return configured
    registry_reader = getattr(urllib.request, "getproxies_registry", None)
    if not callable(registry_reader):
        return configured
    try:
        system = registry_reader()
    except OSError:
        return configured
    return {**system, **configured} if isinstance(system, dict) else configured
