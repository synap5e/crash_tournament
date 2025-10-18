"""
Core dataclasses for the crash tournament system.

Defines Crash and OrdinalResult models with validation.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from .exceptions import ValidationError


@dataclass
class Crash:
    """Represents a crash report as a black box file."""

    crash_id: str
    file_path: str
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Validate crash data."""
        if not self.crash_id:
            raise ValidationError("crash_id cannot be empty")
        if not self.file_path:
            raise ValidationError("file_path cannot be empty")


@dataclass
class OrdinalResult:
    """Result of ordinal ranking evaluation."""

    ordered_ids: list[str]
    raw_output: str
    parsed_result: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    judge_id: str = "unknown"

    def __post_init__(self) -> None:
        """Validate ordinal result data."""
        if not self.ordered_ids:
            raise ValidationError("ordered_ids cannot be empty")
