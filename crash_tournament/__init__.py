"""
Crash Tournament - Adaptive Comparative Judging System

A system for ranking crash reports by exploitability using TrueSkill ranking
with uncertainty-based sampling and configurable n-way comparisons.
"""

from .models import Crash, OrdinalResult, GradedResult
from .interfaces import CrashFetcher, Judge, Storage, Ranker, Selector
from .orchestrator import Orchestrator, RunConfig

__version__ = "0.1.0"
__all__ = [
    "Crash",
    "OrdinalResult", 
    "GradedResult",
    "CrashFetcher",
    "Judge",
    "Storage",
    "Ranker",
    "Selector",
    "Orchestrator",
    "RunConfig",
]
