"""
Crash fetcher implementations.

Provides implementations of the CrashFetcher interface for loading crash data
from various sources.

Available implementations:
- DirectoryCrashFetcher: Loads crashes from directory structure with JSON files
"""

from .directory_fetcher import DirectoryCrashFetcher

__all__ = ["DirectoryCrashFetcher"]
