"""
Core dataclasses for the crash tournament system.

Defines Crash, OrdinalResult, and GradedResult models with validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class Crash:
    """Represents a crash report as a black box file."""
    
    crash_id: str
    file_path: str
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Validate crash data."""
        if not self.crash_id:
            raise ValueError("crash_id cannot be empty")
        if not self.file_path:
            raise ValueError("file_path cannot be empty")


@dataclass
class OrdinalResult:
    """Result of ordinal ranking evaluation."""
    
    ordered_ids: List[str]
    raw_output: str
    parsed_result: dict
    timestamp: float = field(default_factory=time.time)
    judge_id: str = "unknown"
    group_size: int = 0
    
    def __post_init__(self):
        """Validate ordinal result data."""
        if not self.ordered_ids:
            raise ValueError("ordered_ids cannot be empty")
        if len(self.ordered_ids) != self.group_size:
            raise ValueError(f"ordered_ids length {len(self.ordered_ids)} != group_size {self.group_size}")


@dataclass
class GradedResult:
    """Result of graded evaluation (for future use)."""
    
    grades: Dict[str, float]
    raw_output: str
    parsed_result: dict
    timestamp: float = field(default_factory=time.time)
    judge_id: str = "unknown"
    group_size: int = 0
    
    def __post_init__(self):
        """Validate graded result data."""
        if not self.grades:
            raise ValueError("grades cannot be empty")
        if len(self.grades) != self.group_size:
            raise ValueError(f"grades length {len(self.grades)} != group_size {self.group_size}")
