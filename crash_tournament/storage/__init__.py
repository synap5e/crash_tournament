"""
Storage implementations.

Provides implementations of the Storage interface for persisting tournament
data and system state.

Available implementations:
- JSONLStorage: Persists observations to JSONL files and snapshots to JSON
- SQLiteStorage: (Planned) SQLite-based storage for better querying capabilities
"""

from .jsonl_storage import JSONLStorage

__all__ = ["JSONLStorage"]
