"""
Abstract base classes defining the interfaces for the crash tournament system.

All interfaces are synchronous to avoid asyncio complexity in core interfaces.
"""

from abc import ABC, abstractmethod
from typing import Iterable, Sequence, Optional, Any
from .models import Crash, OrdinalResult, GradedResult


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
    """Interface for evaluating crash groups."""
    
    @abstractmethod
    def evaluate_group(self, crashes: Sequence[Crash], *, grading: bool = False) -> OrdinalResult:
        """
        Synchronous evaluation of a crash group.
        
        May block. Caller runs in threadpool for concurrency.
        
        Args:
            crashes: Sequence of crashes to evaluate
            grading: If True, return GradedResult instead of OrdinalResult
            
        Returns:
            OrdinalResult with ordered crash IDs and rationale
        """
        pass


class Storage(ABC):
    """Interface for persisting results and state."""
    
    @abstractmethod
    def persist_ordinal(self, res: OrdinalResult) -> None:
        """Persist an ordinal evaluation result."""
        pass

    @abstractmethod
    def load_observations(self) -> Iterable[OrdinalResult]:
        """Load all persisted ordinal results."""
        pass

    @abstractmethod
    def save_snapshot(self, state: dict[str, Any]) -> None:
        """
        Save system state snapshot.
        
        Include checksum and timestamp per doc line 180.
        """
        pass

    @abstractmethod
    def load_snapshot(self) -> Optional[dict[str, Any]]:
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
    def snapshot(self) -> dict[str, Any]:
        """Export current ranking state."""
        pass

    @abstractmethod
    def load_snapshot(self, state: dict[str, Any]) -> None:
        """Load ranking state from snapshot."""
        pass

    @abstractmethod
    def track_evaluation_by_phase(self, crash_id: str, is_seed_phase: bool) -> None:
        """Track evaluation count by phase."""
        pass

    @abstractmethod  
    def get_eval_count(self, crash_id: str) -> int:
        """Get total evaluation count for a crash."""
        pass

    @abstractmethod
    def get_seed_eval_count(self, crash_id: str) -> int:
        """Get number of times crash was evaluated in seed phase."""
        pass

    @abstractmethod
    def get_adaptive_eval_count(self, crash_id: str) -> int:
        """Get number of times crash was evaluated in adaptive phase."""
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
    """Interface for selecting crash groups to evaluate."""
    
    @abstractmethod
    def next_groups(self, all_crash_ids: Sequence[str], k: int, budget: int) -> Sequence[Sequence[str]]:
        """
        Return list of crash ID groups to evaluate.
        
        Args:
            all_crash_ids: All available crash IDs to select from
            k: Group size
            budget: Number of groups to return
            
        Implements uncertainty-based sampling per doc lines 186–193.
        """
        pass
