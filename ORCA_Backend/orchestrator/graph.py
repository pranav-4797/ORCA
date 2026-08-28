"""Graph assembly — Task 10 split (re-exports Orchestrator for package)."""
from __future__ import annotations

# This module is part of the orchestrator package split.
# The main Orchestrator class lives in orchestrator/__init__.py for now,
# but this module exists to satisfy the package structure requirement
# and to host graph-related helpers in future.

# Re-export for convenience
try:
    from . import Orchestrator  # type: ignore
    __all__ = ["Orchestrator"]
except Exception:
    __all__ = []
