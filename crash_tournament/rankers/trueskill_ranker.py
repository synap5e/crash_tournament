"""
TrueSkill ranker implementation.

Uses trueskill package with k-way to pairwise conversion and proper weighting.
"""

import threading
from typing import cast, override, TYPE_CHECKING

if TYPE_CHECKING:
    from loguru._logger import Logger

from trueskill import Rating, rate_1vs1, setup  # type: ignore[import-untyped]

from ..interfaces import Ranker, RankerState
from ..models import OrdinalResult
from ..logging_config import get_logger


class TrueSkillRanker(Ranker):
    """
    TrueSkill-based ranker with k-way to pairwise conversion.
    
    Converts k-way ordinal results to k-1 sequential pairwise wins
    and applies proper weighting to avoid overconfidence.
    
    Thread Safety: This ranker is designed to be used only from the main thread.
    The orchestrator ensures thread safety by calling all ranker operations
    (update_with_ordinal, get_score, etc.) from the main thread, while using
    ThreadPoolExecutor only for judge evaluations.
    """
    
    def __init__(self, mu: float = 25.0, sigma: float = 8.333333333333334, tau: float = 0.08333333333333334):
        """
        Initialize TrueSkill ranker.
        
        Args:
            mu: Initial mean rating
            sigma: Initial standard deviation
            tau: Dynamic factor for rating updates
        """
        self.mu: float = mu
        self.sigma: float = sigma
        self.tau: float = tau
        
        # Store ratings per crash
        self.ratings = dict[str, Rating]()
        
        # Statistics tracking
        self.eval_counts = dict[str, int]()  # How many times each crash was evaluated
        self.win_counts = dict[str, int]()    # How many times each crash won
        self.rankings = dict[str, list[int]]()  # All rankings for each crash
        self.group_sizes = dict[str, list[int]]()  # Group sizes for each evaluation
        
        # Thread safety lock
        self._lock: threading.Lock = threading.Lock()
        
        # Setup logger
        self.logger: Logger = get_logger("trueskill_ranker")
        
        # Configure trueskill
        _ = setup(mu=mu, sigma=sigma, tau=tau)
        self.logger.info(f"TrueSkill ranker initialized: mu={mu}, sigma={sigma}, tau={tau}")
    
    def _get_or_create_rating(self, crash_id: str) -> Rating:
        """Get existing rating or create new one with default values.
        
        Args:
            crash_id: Unique identifier for the crash
            
        Returns:
            TrueSkill Rating object for the crash
        """
        """Get existing rating or create default one for unseen crash."""
        if crash_id not in self.ratings:
            self.ratings[crash_id] = Rating(mu=self.mu, sigma=self.sigma)  # type: ignore[arg-type]
        return self.ratings[crash_id]
    

    @override
    def update_with_ordinal(self, res: OrdinalResult, weight: float = 1.0) -> None:
        """
        Update rankings with ordinal result using k-way to pairwise conversion.
        
        Converts [a,b,c,d] to sequential wins: a>b, b>c, c>d
        Applies weight scaling to avoid overconfidence from k-way expansion.
        Thread-safe implementation.
        """
        ordered_ids = res.ordered_ids
        
        if len(ordered_ids) < 2:
            self.logger.debug("Skipping update: need at least 2 items for comparison")
            return  # Need at least 2 items for comparison
        
        self.logger.debug(f"Updating rankings for {ordered_ids} with weight {weight}")
        
        # Thread-safe update with lock
        with self._lock:
            # Track evaluation counts for all crashes in this group
            for crash_id in ordered_ids:
                self.eval_counts[crash_id] = self.eval_counts.get(crash_id, 0) + 1
            
            # Track wins for each crash (number of other crashes it beat)
            group_size = len(ordered_ids)
            for rank, crash_id in enumerate(ordered_ids):
                # A crash beats all crashes ranked below it
                wins = group_size - rank - 1
                self.win_counts[crash_id] = self.win_counts.get(crash_id, 0) + wins
                if crash_id not in self.rankings:
                    self.rankings[crash_id] = []
                    self.group_sizes[crash_id] = []
                self.rankings[crash_id].append(rank + 1)  # 1-based ranking
                self.group_sizes[crash_id].append(group_size)
            
            # Convert k-way to k-1 sequential pairwise wins
            for i in range(len(ordered_ids) - 1):
                winner_id = ordered_ids[i]
                loser_id = ordered_ids[i + 1]
                
                # Get current ratings
                winner_rating = self._get_or_create_rating(winner_id)
                loser_rating = self._get_or_create_rating(loser_id)
                
                # Apply weight by adjusting tau (dynamic factor)
                # Lower weight = more conservative updates (dampen tau)
                adjusted_tau = self.tau * weight if weight > 0 else self.tau
                
                # Update ratings with adjusted tau
                # NOTE: This modifies global TrueSkill state, but it's NOT a thread safety issue
                # because TrueSkillRanker is only accessed from the main thread. The orchestrator
                # uses ThreadPoolExecutor for judge evaluations, but all ranker operations
                # (update_with_ordinal, get_score, etc.) are explicitly called from the main
                # thread in _process_completed_futures() to ensure thread safety.
                original_tau = self.tau
                _ = setup(mu=self.mu, sigma=self.sigma, tau=adjusted_tau)
                
                new_winner, new_loser = rate_1vs1(winner_rating, loser_rating, drawn=False)  # type: ignore[misc]
                
                # Restore original tau
                _ = setup(mu=self.mu, sigma=self.sigma, tau=original_tau)
                
                # Update stored ratings
                self.ratings[winner_id] = new_winner
                self.ratings[loser_id] = new_loser
                
                self.logger.info(f"Score update: {winner_id} vs {loser_id}")
                self.logger.info(f"  {winner_id}: {winner_rating.mu:.2f}->{new_winner.mu:.2f} (σ: {winner_rating.sigma:.2f}->{new_winner.sigma:.2f})")  # type: ignore[attr-defined]
                self.logger.info(f"  {loser_id}: {loser_rating.mu:.2f}->{new_loser.mu:.2f} (σ: {loser_rating.sigma:.2f}->{new_loser.sigma:.2f})")  # type: ignore[attr-defined]
    
    @override
    def get_score(self, crash_id: str) -> float:
        """Get current score (mu) for a crash."""
        rating = self._get_or_create_rating(crash_id)
        return rating.mu  # type: ignore[attr-defined]
    
    @override
    def get_uncertainty(self, crash_id: str) -> float:
        """Get current uncertainty (sigma) for a crash."""
        rating = self._get_or_create_rating(crash_id)
        return rating.sigma  # type: ignore[attr-defined]
    
    @override
    def snapshot(self) -> RankerState:
        """Export current ranking state as serializable dict."""
        return {
            "ratings": {
                crash_id: {
                    "mu": rating.mu,  # type: ignore[attr-defined]
                    "sigma": rating.sigma  # type: ignore[attr-defined]
                }
                for crash_id, rating in self.ratings.items()
            },
            "statistics": {
                "eval_counts": self.eval_counts,
                "win_counts": self.win_counts,
                "rankings": self.rankings,
                "group_sizes": self.group_sizes
            }
        }
    
    @override
    def load_snapshot(self, state: RankerState) -> None:
        """Load ranking state from snapshot."""
        self.ratings.clear()
        self.eval_counts.clear()
        self.win_counts.clear()
        self.rankings.clear()
        self.group_sizes.clear()
        
        # Handle both old and new snapshot formats
        if "ratings" in state:
            # New format with statistics
            ratings_data = state["ratings"]
            statistics = state.get("statistics", {})
            self.eval_counts = cast(dict[str, int], dict(statistics.get("eval_counts", {})))
            self.win_counts = cast(dict[str, int], dict(statistics.get("win_counts", {})))
            self.rankings = cast(dict[str, list[int]], dict(statistics.get("rankings", {})))
            self.group_sizes = cast(dict[str, list[int]], dict(statistics.get("group_sizes", {})))
        else:
            # Old format - just ratings
            ratings_data = state
        
        for crash_id, rating_data in ratings_data.items():
            rating_dict = rating_data  # type: ignore[assignment]
            self.ratings[crash_id] = Rating(
                mu=rating_dict["mu"],  # type: ignore[arg-type]
                sigma=rating_dict["sigma"]  # type: ignore[arg-type]
            )
    
    def get_all_scores(self) -> dict[str, float]:
        """Get all crash scores for debugging."""
        return {crash_id: rating.mu for crash_id, rating in self.ratings.items()}  # type: ignore[attr-defined]
    
    def get_all_uncertainties(self) -> dict[str, float]:
        """Get all crash uncertainties for debugging."""
        return {crash_id: rating.sigma for crash_id, rating in self.ratings.items()}  # type: ignore[attr-defined]
    
    @override
    def get_total_eval_count(self, crash_id: str) -> int:
        """Get total evaluation count for a crash."""
        return self.eval_counts.get(crash_id, 0)
    
    @override
    def get_win_percentage(self, crash_id: str) -> float:
        """Get win percentage for a crash."""
        eval_count = self.get_total_eval_count(crash_id)
        if eval_count == 0:
            return 0.0
        win_count = self.win_counts.get(crash_id, 0)
        
        # Calculate total possible wins using actual group sizes
        group_sizes = self.group_sizes.get(crash_id, [])
        if not group_sizes:
            return 0.0
        
        total_possible_wins = sum(group_size - 1 for group_size in group_sizes)
        if total_possible_wins == 0:
            return 0.0
        return (win_count / total_possible_wins) * 100.0
    
    @override
    def get_average_ranking(self, crash_id: str) -> float:
        """Get average ranking for a crash."""
        rankings = self.rankings.get(crash_id, [])
        if not rankings:
            return 0.0
        return sum(rankings) / len(rankings)
    
    def get_all_statistics(self) -> dict[str, dict[str, float]]:
        """Get all statistics for all crashes."""
        stats = {}
        for crash_id in self.ratings.keys():
            stats[crash_id] = {
                'score': self.get_score(crash_id),
                'eval_count': self.get_total_eval_count(crash_id),
                'win_percentage': self.get_win_percentage(crash_id),
                'avg_ranking': self.get_average_ranking(crash_id)
            }
        return stats