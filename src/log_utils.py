from __future__ import annotations

import logging

_logger = logging.getLogger("study_agent")
_logger.setLevel(logging.WARNING)

if not _logger.handlers:
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _logger.addHandler(_ch)


def get_logger() -> logging.Logger:
    return _logger
