"""
Abstract base classes defining the interfaces for the crash tournament system.

All interfaces are synchronous to avoid asyncio complexity in core interfaces.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import TypedDict
from .models import Crash, OrdinalResult


class RankerStatistics(TypedDict):
    """TypedDict for ranker statistics."""
    eval_counts: dict[str, int]
    win_counts: dict[str, int]
    rankings: dict[str, list[int]]
    group_sizes: dict[str, list[int]]


class RankerState(TypedDict):
    """TypedDict for ranker snapshot state."""
    ratings: dict[str, dict[str, float]]  # crash_id -> {"mu": float, "sigma": float}
    statistics: RankerStatistics


class SystemState(TypedDict):
    """TypedDict for system snapshot state."""
    ranker_state: RankerState
    runtime_state: dict[str, int]  # evaluated_matchups, etc.


class JudgeError(Exception):
    """Base exception for all judge-related errors."""
    pass


class CrashFetcher(ABC):
    """Interface for fetching crash data."""
    
    @abstractmethod
    def list_crashes(self) -> Iterable[Crash]:
        """Return all available crashes."""
        pass

    @abstractmethod
    def get_crash(self, crash_id: str) -> Crash:
        """Get a specific crash by ID."""
        pass


class Judge(ABC):
    """Interface for evaluating crash matchups."""
    
    @abstractmethod
    def evaluate_matchup(self, crashes: Sequence[Crash]) -> OrdinalResult:
        """
        Synchronous evaluation of a crash matchup.
        
        May block. Caller runs in threadpool for concurrency.
        
        Args:
            crashes: Sequence of crashes to evaluate
            
        Returns:
            OrdinalResult with ordered crash IDs and rationale
        """
        pass


class Storage(ABC):
    """Interface for persisting results and state."""
    
    @abstractmethod
    def persist_matchup_result(self, res: OrdinalResult) -> None:
        """Persist a matchup evaluation result."""
        pass

    @abstractmethod
    def load_observations(self) -> Iterable[OrdinalResult]:
        """Load all persisted ordinal results."""
        pass

    @abstractmethod
    def save_snapshot(self, state: SystemState) -> None:
        """
        Save system state snapshot.
        
        Include checksum and timestamp per doc line 180.
        """
        pass

    @abstractmethod
    def load_snapshot(self) -> SystemState | None:
        """Load system state snapshot."""
        pass


class Ranker(ABC):
    """Interface for ranking crashes by exploitability."""
    
    @abstractmethod
    def update_with_ordinal(self, res: OrdinalResult, weight: float = 1.0) -> None:
        """
        Update rankings with ordinal result.
        
        Use 1/(k-1) to scale k-way conversions per doc lines 146–147.
        """
        pass

    @abstractmethod
    def get_score(self, crash_id: str) -> float:
        """Get current score (mu) for a crash."""
        pass

    @abstractmethod
    def get_uncertainty(self, crash_id: str) -> float:
        """Get current uncertainty (sigma) for a crash."""
        pass

    @abstractmethod
    def snapshot(self) -> RankerState:
        """Export current ranking state."""
        pass

    @abstractmethod
    def load_snapshot(self, state: RankerState) -> None:
        """Load ranking state from snapshot."""
        pass

    @abstractmethod  
    def get_total_eval_count(self, crash_id: str) -> int:
        """Get total evaluation count for a crash."""
        pass

    @abstractmethod
    def get_win_percentage(self, crash_id: str) -> float:
        """Get win percentage for a crash."""
        pass

    @abstractmethod
    def get_average_ranking(self, crash_id: str) -> float:
        """Get average ranking for a crash."""
        pass


class Selector(ABC):
    """Interface for selecting crash matchups to evaluate."""
    
    @abstractmethod
    def select_matchup(self, all_crash_ids: Sequence[str], matchup_size: int) -> Sequence[str] | None:
        """
        Select crash ID matchup to evaluate.
        
        Args:
            all_crash_ids: All available crash IDs to select from
            matchup_size: Number of crashes per matchup
            
        Returns:
            List of crash IDs for matchup, or None if no more matchups available
        """
        pass
