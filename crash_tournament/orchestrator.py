"""
Orchestrator for crash tournament evaluation.

Coordinates fetcher, judge, storage, ranker, and selector components.
Uses just-in-time work queue pattern for maximum adaptiveness.
"""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, Future
from dataclasses import dataclass
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger

from .interfaces import CrashFetcher, Judge, Storage, Ranker, Selector, SystemState
from .models import Crash, OrdinalResult
from .logging_config import get_logger

# Constants for failure threshold logic
EARLY_ABORT_THRESHOLD = 4      # Abort if 100% of first 4 evaluations fail
LATE_ABORT_THRESHOLD = 50     # Only check failure rate after 50+ evaluations
FAILURE_RATE_LIMIT = 0.2      # Abort if >20% failure rate after threshold
MILESTONE_INTERVAL = 1        # Print milestone updates every 1 evaluation


@dataclass
class RunConfig:
    """Configuration for tournament run."""
    
    matchup_size: int = 4  # crashes per matchup, validate 2 ≤ size ≤ 7
    budget: int = 1000  # total matchup evaluations allowed
    max_workers: int = 4  # thread pool size
    snapshot_every: int = 10  # print progress every N matchups (snapshots saved on every update)
    
    def __post_init__(self):
        """Validate configuration."""
        if not (2 <= self.matchup_size <= 7):
            raise ValueError(f"matchup_size must be between 2 and 7, got {self.matchup_size}")
        if self.budget <= 0:
            raise ValueError(f"budget must be positive, got {self.budget}")
        if self.max_workers <= 0:
            raise ValueError(f"max_workers must be positive, got {self.max_workers}")


class Orchestrator:
    """Main orchestrator for crash tournament evaluation."""
    
    def __init__(
        self,
        fetcher: CrashFetcher,
        judge: Judge,
        storage: Storage,
        ranker: Ranker,
        selector: Selector,
        config: RunConfig,
        output_dir: str
    ):
        """Initialize orchestrator with all components."""
        self.fetcher: CrashFetcher = fetcher
        self.judge: Judge = judge
        self.storage: Storage = storage
        self.ranker: Ranker = ranker
        self.selector: Selector = selector
        self.config: RunConfig = config
        self.output_dir: str = output_dir
        
        # Runtime state
        self.evaluated_matchups: int = 0
        
        # In-flight crash tracking to prevent concurrent evaluation
        self.in_flight_crashes: set[str] = set()
        
        # Exception tolerance tracking
        self.total_evaluations: int = 0  # Total attempted (including failures)
        self.failed_evaluations: int = 0  # Count of failures
        self.failure_log = list[tuple[Sequence[str], str, str]]()  # List of (matchup, exception_type, exception_msg)
        
        # Milestone tracking
        self.last_milestone: int = 0  # Last milestone (multiple of 50) where we printed
        
        # Setup logger
        self.logger: Logger = get_logger("orchestrator")
        
    def run(self) -> dict[str, float]:
        """Run tournament using just-in-time work queue pattern."""
        self.logger.info(f"Starting crash tournament with config: {self.config}")
        print(f"Starting crash tournament with config: {self.config}")
        
        # Load snapshot if exists
        snapshot = self.storage.load_snapshot()
        if snapshot:
            self._load_snapshot(snapshot)
            self.logger.info(f"Resumed from snapshot: {self.evaluated_matchups} matchups evaluated")
            print(f"Resumed from snapshot: {self.evaluated_matchups} matchups evaluated")
        
        # Get all crash IDs ONCE (main thread)
        crashes = list(self.fetcher.list_crashes())
        crash_ids = [c.crash_id for c in crashes]
        self.logger.info(f"Loaded {len(crash_ids)} crashes for evaluation")
        
        # Pure worker function (module-level, no state access)
        def evaluate_matchup_worker(crashes: Sequence[Crash], judge: Judge) -> OrdinalResult:
            """Pure worker function - receives data, returns result."""
            return judge.evaluate_matchup(crashes)
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = dict[Future[OrdinalResult], tuple[Sequence[str], list[Crash]]]()  # future -> (matchup_ids, crashes) mapping for error reporting
            
            # Keep workers fed while budget allows
            while self.evaluated_matchups < self.config.budget:
                # Process completed futures (main thread updates state)
                self._process_completed_futures(futures)
                
                # Track in-flight work to avoid budget overshoot
                in_flight = len(futures)
                remaining_budget = self.config.budget - self.evaluated_matchups - in_flight
                
                # Keep workers busy - submit new work up to max_workers
                while len(futures) < self.config.max_workers and remaining_budget > 0:
                    # Filter out crashes currently being evaluated
                    available_crashes = [c for c in crash_ids if c not in self.in_flight_crashes]
                    
                    # Check if we have enough available crashes
                    if len(available_crashes) < self.config.matchup_size:
                        self.logger.info(f"Insufficient available crashes ({len(available_crashes)} available, {len(self.in_flight_crashes)} in-flight, {self.config.matchup_size} needed)")
                        # Don't submit more work, but continue to process in-flight futures
                        # This handles edge cases where parallelism > possible concurrent matchups
                        break  # Exit inner work submission loop, will wait for completions in outer loop
                    
                    # Main thread generates matchup IDs
                    matchup_ids = self.selector.select_matchup(available_crashes, self.config.matchup_size)
                    if matchup_ids is None:
                        self.logger.info("Selector returned no more matchups")
                        break
                    
                    # Main thread fetches crash data
                    crashes = [self.fetcher.get_crash(crash_id) for crash_id in matchup_ids]
                    
                    # Submit pure work to worker (crashes + judge, no state access)
                    future = executor.submit(evaluate_matchup_worker, crashes, self.judge)
                    futures[future] = (matchup_ids, crashes)
                    
                    # Mark these crashes as in-flight
                    self.in_flight_crashes.update(matchup_ids)
                    self.logger.debug(f"Marked in-flight: {matchup_ids}, total in-flight: {len(self.in_flight_crashes)}")
                    
                    # Recalculate remaining budget
                    in_flight = len(futures)
                    remaining_budget = self.config.budget - self.evaluated_matchups - in_flight
                
                # Wait for at least one to complete before checking for more work
                if futures:
                    _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                else:
                    self.logger.info("No work in flight and cannot generate more matchups")
                    break  # No work in flight and can't generate more
            
            # Drain remaining futures
            self.logger.info(f"Draining {len(futures)} remaining futures")
            self._process_completed_futures(futures, wait_all=True)
        
        # Save final snapshot
        self._save_snapshot()
        
        self.logger.info(f"Tournament complete: {self.evaluated_matchups} matchups evaluated")
        print(f"Tournament complete: {self.evaluated_matchups} matchups evaluated")
        return self._get_final_rankings()
    
    def _load_snapshot(self, snapshot: SystemState) -> None:
        """Load state from snapshot (main thread only)."""
        self.ranker.load_snapshot(snapshot['ranker_state'])
        runtime_state = snapshot.get('runtime_state', {})
        self.evaluated_matchups = runtime_state.get('evaluated_matchups', 0)
        self.total_evaluations = runtime_state.get('total_evaluations', 0)
        self.failed_evaluations = runtime_state.get('failed_evaluations', 0)
        self.last_milestone = runtime_state.get('last_milestone', 0)

    def _process_completed_futures(self, futures: dict[Future[OrdinalResult], tuple[Sequence[str], list[Crash]]], wait_all: bool = False) -> None:
        """
        Process completed futures and update state (main thread only).
        
        This method handles the results from worker threads, updating the ranker,
        storage, and in-flight tracking. It's called from the main thread to ensure
        thread safety. Workers are read-only and only return results.
        
        Args:
            futures: Dictionary mapping futures to their matchup data
            wait_all: If True, process all futures; if False, only process completed ones
        """
        done_futures = []
        
        if wait_all:
            done_futures = list(futures.keys())
        else:
            done_futures = [f for f in futures.keys() if f.done()]
        
        for future in done_futures:
            matchup_ids, _ = futures.pop(future)
            
            try:
                result = future.result()
                
                # Persist result
                self.storage.persist_matchup_result(result)
                
                # Update ranker (main thread) - compute weight inline
                if self.config.matchup_size <= 1:
                    raise ValueError(f"matchup_size must be >= 2, got {self.config.matchup_size}")
                weight = 1.0 / (self.config.matchup_size - 1)
                self.ranker.update_with_ordinal(result, weight=weight)
                
                # Update counters (main thread)
                self.evaluated_matchups += 1
                self.total_evaluations += 1
                
                # Release crashes from in-flight tracking
                self.in_flight_crashes.difference_update(matchup_ids)
                self.logger.debug(f"Released from in-flight: {matchup_ids}")
                
                self.logger.info(f"Completed matchup {self.evaluated_matchups}/{self.config.budget}: {matchup_ids}")
                
                # Snapshot on every update for complete historical record
                self._save_snapshot()
                
                # Print progress every N evaluations
                if self.evaluated_matchups % self.config.snapshot_every == 0:
                    self._print_progress()
                
                # Check for milestones (every MILESTONE_INTERVAL)
                if self.evaluated_matchups % MILESTONE_INTERVAL == 0 and self.evaluated_matchups > self.last_milestone:
                    self._print_milestone()
                    self.last_milestone = self.evaluated_matchups
                    
            except Exception as e:
                self.logger.error(f"Evaluation failed for matchup {matchup_ids}: {e}")
                self.failed_evaluations += 1
                self.total_evaluations += 1
                self.failure_log.append((matchup_ids, type(e).__name__, str(e)))
                
                # Release crashes from in-flight tracking even on failure
                self.in_flight_crashes.difference_update(matchup_ids)
                self.logger.debug(f"Released from in-flight (after error): {matchup_ids}")
                    
                # Abort if failure rate too high
                if self.total_evaluations >= EARLY_ABORT_THRESHOLD and self.failed_evaluations == self.total_evaluations:
                    raise RuntimeError(f"100% failure rate in first {EARLY_ABORT_THRESHOLD} evaluations - aborting")
                    
                if self.total_evaluations >= LATE_ABORT_THRESHOLD:
                    failure_rate = self.failed_evaluations / self.total_evaluations
                    if failure_rate > FAILURE_RATE_LIMIT:
                        raise RuntimeError(f"Failure rate {failure_rate:.1%} exceeds {FAILURE_RATE_LIMIT:.0%} threshold - aborting")

    def _save_snapshot(self) -> None:
        """Save snapshot (main thread only)."""
        snapshot: SystemState = {
            'ranker_state': self.ranker.snapshot(),
            'runtime_state': {
                'evaluated_matchups': self.evaluated_matchups,
                'total_evaluations': self.total_evaluations,
                'failed_evaluations': self.failed_evaluations,
                'last_milestone': self.last_milestone,
            }
        }
        self.storage.save_snapshot(snapshot)
        self.logger.debug(f"Saved snapshot at {self.evaluated_matchups} matchups")

    def _print_progress(self) -> None:
        """Print progress (main thread only)."""
        progress = (self.evaluated_matchups / self.config.budget) * 100
        self.logger.info(f"Progress: {self.evaluated_matchups}/{self.config.budget} ({progress:.1f}%), {len(self.in_flight_crashes)} crashes in-flight")
        print(f"Progress: {self.evaluated_matchups}/{self.config.budget} matchups ({progress:.1f}%), {len(self.in_flight_crashes)} crashes in-flight")

    def _print_milestone(self) -> None:
        """Print milestone summary (main thread only)."""
        print(f"\n{'='*60}")
        print(f"Milestone: {self.evaluated_matchups} matchups evaluated")
        print(f"Success rate: {(1 - self.failed_evaluations/max(1, self.total_evaluations))*100:.1f}%")
        
        # Print top 5 crashes
        top_crashes = self._get_top_scores(n=5)
        print("\nTop 5 Crashes:")
        for i, (crash_id, score, uncertainty) in enumerate(top_crashes, 1):
            print(f"  {i}. {crash_id}: μ={score:.3f}, σ={uncertainty:.3f}")
        print(f"{'='*60}\n")
    
    def _get_top_scores(self, n: int = 5) -> list[tuple[str, float, float]]:
        """Get top N crash scores for logging."""
        crashes = list(self.fetcher.list_crashes())
        scores = list[tuple[str, float, float]]()
        
        for crash in crashes:
            score = self.ranker.get_score(crash.crash_id)
            uncertainty = self.ranker.get_uncertainty(crash.crash_id)
            scores.append((crash.crash_id, score, uncertainty))
        
        # Sort by score (mu) descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:n]
    
    def _get_final_rankings(self) -> dict[str, float]:
        """Get final crash rankings."""
        crashes = list(self.fetcher.list_crashes())
        rankings = dict[str, float]()
        
        for crash in crashes:
            score = self.ranker.get_score(crash.crash_id)
            rankings[crash.crash_id] = score
        
        # Sort by score (highest first)
        return dict(sorted(rankings.items(), key=lambda x: x[1], reverse=True))