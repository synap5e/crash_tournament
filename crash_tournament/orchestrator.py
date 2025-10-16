"""
Orchestrator engine for the crash tournament system.

Manages the main evaluation loop with dependency injection and thread pool execution.
"""

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .interfaces import CrashFetcher, Judge, Storage, Ranker, Selector
from .models import Crash, OrdinalResult
from .logging_config import get_logger


@dataclass
class RunConfig:
    """Configuration for tournament run."""
    
    k: int = 4  # group size, validate 2 ≤ k ≤ 7
    seed_groups: int = 200
    groups_per_round: int = 50
    max_rounds: Optional[int] = None
    budget: int = 1000  # total judge calls allowed
    weight_scale: float = 1.0  # computed as 1/(k-1)
    repeats_threshold: Optional[float] = None  # sigma threshold for re-eval
    max_workers: int = 4  # thread pool size
    
    def __post_init__(self):
        """Validate configuration."""
        if not (2 <= self.k <= 7):
            raise ValueError(f"k must be between 2 and 7, got {self.k}")
        if self.budget <= 0:
            raise ValueError(f"budget must be positive, got {self.budget}")
        if self.max_workers <= 0:
            raise ValueError(f"max_workers must be positive, got {self.max_workers}")
        
        # Compute weight scale
        self.weight_scale = 1.0 / (self.k - 1)


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
        output_dir = None,
    ):
        """Initialize orchestrator with dependency injection."""
        self.fetcher = fetcher
        self.judge = judge
        self.storage = storage
        self.ranker = ranker
        self.selector = selector
        self.config = config
        self.output_dir = output_dir
        
        # Runtime state
        self.evaluated_groups = 0
        self.current_round = 0
        
        # Exception tolerance tracking
        self.total_evaluations = 0  # Total attempted (including failures)
        self.failed_evaluations = 0  # Count of failures
        self.failure_log = []  # List of (group, exception_type, exception_msg)
        
        # Milestone tracking
        self.last_milestone = 0  # Last milestone (multiple of 50) where we printed
        
        # Setup logger
        self.logger = get_logger("orchestrator")
        
    def _seed_phase(self) -> List[List[str]]:
        """
        Generate initial random groups for seeding.
        
        Aim for each crash appearing 2–3 times.
        """
        self.logger.info("Starting seed phase")
        crashes = list(self.fetcher.list_crashes())
        if not crashes:
            self.logger.error("No crashes available for evaluation")
            raise ValueError("No crashes available for evaluation")
        
        self.logger.info(f"Found {len(crashes)} crashes for evaluation")
        crash_ids = [crash.crash_id for crash in crashes]
        groups = []
        
        # Generate random groups
        self.logger.info(f"Generating {self.config.seed_groups} seed groups")
        for _ in range(self.config.seed_groups):
            group = random.sample(crash_ids, min(self.config.k, len(crash_ids)))
            groups.append(group)
        
        self.logger.info(f"Generated {len(groups)} seed groups")
        return groups
    
    def _evaluate_groups(self, groups: Sequence[Sequence[str]]) -> List[OrdinalResult]:
        """
        Evaluate groups using thread pool with exception tolerance.
        
        Tolerates up to 20% LLM failures. Aborts if:
        - 100% of first 4 calls fail (agent is broken)
        - >20% failure rate after 50 calls (unacceptable failure rate)
        """
        self.logger.info(f"Evaluating {len(groups)} groups with {self.config.max_workers} workers")
        results = []
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit all evaluation tasks
            future_to_group = {}
            for group in groups:
                crashes = [self.fetcher.get_crash(crash_id) for crash_id in group]
                future = executor.submit(self.judge.evaluate_group, crashes)
                future_to_group[future] = group
            
            # Process completed evaluations
            for future in as_completed(future_to_group):
                group = future_to_group[future]
                self.total_evaluations += 1
                
                try:
                    result = future.result()
                    
                    # Log the evaluation result
                    self.logger.info(f"Group {group} ranked: {result.ordered_ids}")
                    if result.parsed_result:
                        # Log the full parsed result for debugging
                        import json
                        self.logger.info(f"Full parsed result: {json.dumps(result.parsed_result, indent=2)}")
                        
                        # Also show rationale if available
                        rationale = result.parsed_result.get('rationale_top', 
                                                             result.parsed_result.get('rationale', 
                                                                                     'No rationale provided'))
                        self.logger.info(f"Rationale: {rationale}")
                    
                    # Persist result
                    self.storage.persist_ordinal(result)
                    # Update ranker with weight scaling
                    self.ranker.update_with_ordinal(result, weight=self.config.weight_scale)
                    results.append(result)
                    self.evaluated_groups += 1
                    
                    # Check for milestone (multiple of 50)
                    self._check_and_print_milestone()
                    
                    # Log current top scores
                    if self.evaluated_groups % 5 == 0:  # Every 5 evaluations
                        top_scores = self._get_top_scores(5)
                        self.logger.info(f"Current top scores: {top_scores}")
                        
                        # Show mini progress update during long evaluation batches
                        if len(groups) > 10:  # Only for large batches
                            budget_progress = (self.evaluated_groups / self.config.budget) * 100
                            print(f"  Progress: {self.evaluated_groups}/{self.config.budget} ({budget_progress:.1f}%) - Top: {top_scores[0][0]} ({top_scores[0][1]:.3f})")
                    
                    self.logger.debug(f"Evaluated group {group}, total: {self.evaluated_groups}")
                    
                except Exception as e:
                    # Track failure
                    self.failed_evaluations += 1
                    exception_type = type(e).__name__
                    exception_msg = str(e)
                    self.failure_log.append((group, exception_type, exception_msg))
                    
                    # Log the failure
                    self.logger.error(f"Failed to evaluate group {group}: {exception_type}: {exception_msg}")
                    
                    # Check abort conditions
                    failure_rate = self.failed_evaluations / self.total_evaluations
                    
                    # Early abort: 100% of first 4 calls failed
                    if self.total_evaluations <= 4 and failure_rate == 1.0:
                        self.logger.error(
                            f"ABORTING: 100% of first {self.total_evaluations} evaluations failed. "
                            f"Agent appears to be broken."
                        )
                        print(f"\nERROR: Agent is broken - {self.total_evaluations}/{self.total_evaluations} calls failed")
                        print(f"Last error: {exception_type}: {exception_msg}")
                        raise RuntimeError(
                            f"Agent broken: 100% of first {self.total_evaluations} calls failed. "
                            f"Last error: {exception_type}: {exception_msg}"
                        )
                    
                    # Late abort: >20% failure rate after 50+ calls
                    if self.total_evaluations >= 50 and failure_rate > 0.20:
                        self.logger.error(
                            f"ABORTING: Unacceptable failure rate: "
                            f"{self.failed_evaluations}/{self.total_evaluations} "
                            f"({failure_rate*100:.1f}%) after 50+ calls"
                        )
                        print(f"\nERROR: High failure rate - {self.failed_evaluations}/{self.total_evaluations} "
                              f"({failure_rate*100:.1f}%) evaluations failed")
                        raise RuntimeError(
                            f"Unacceptable failure rate: {self.failed_evaluations}/{self.total_evaluations} "
                            f"({failure_rate*100:.1f}%) failed after 50+ calls"
                        )
                    
                    # Log current failure rate
                    self.logger.warning(
                        f"Current failure rate: {self.failed_evaluations}/{self.total_evaluations} "
                        f"({failure_rate*100:.1f}%)"
                    )
        
        self.logger.info(
            f"Completed evaluation batch: {len(results)} successful, "
            f"{self.failed_evaluations} failed "
            f"({self.failed_evaluations/self.total_evaluations*100:.1f}% failure rate)"
        )
        return results
    
    def _uncertainty_round(self) -> List[OrdinalResult]:
        """
        Run one uncertainty-based evaluation round.
        
        Get groups from selector, evaluate, save snapshot.
        """
        remaining_budget = self.config.budget - self.evaluated_groups
        self.logger.info(f"Starting uncertainty round, remaining budget: {remaining_budget}")
        
        if remaining_budget <= 0:
            self.logger.warning("Budget exhausted, skipping uncertainty round")
            return []
        
        # Get all crash IDs
        crash_ids = [crash.crash_id for crash in self.fetcher.list_crashes()]
        self.logger.debug(f"Available crash IDs: {len(crash_ids)}")
        
        # Get groups from selector with crash IDs
        groups = self.selector.next_groups(
            all_crash_ids=crash_ids, 
            k=self.config.k, 
            budget=remaining_budget
        )
        
        if not groups:
            self.logger.info("No more groups to evaluate from selector")
            return []
        
        self.logger.info(f"Selector returned {len(groups)} groups for evaluation")
        
        # Evaluate groups
        results = self._evaluate_groups(groups)
        
        # Save snapshot
        self.logger.debug("Saving snapshot")
        snapshot = {
            'ranker_state': self.ranker.snapshot(),
            'runtime_state': {
                'evaluated_groups': self.evaluated_groups,
                'current_round': self.current_round,
                'total_evaluations': self.total_evaluations,
                'failed_evaluations': self.failed_evaluations,
                'last_milestone': self.last_milestone,
            }
        }
        self.storage.save_snapshot(snapshot)
        
        return results
    
    def _check_stopping_conditions(self) -> bool:
        """Check if evaluation should stop."""
        # Budget exhausted
        if self.evaluated_groups >= self.config.budget:
            self.logger.info(f"Budget exhausted: {self.evaluated_groups}/{self.config.budget}")
            return True
        
        # Max rounds reached
        if self.config.max_rounds and self.current_round >= self.config.max_rounds:
            self.logger.info(f"Max rounds reached: {self.current_round}/{self.config.max_rounds}")
            return True
        
        # TODO: Top-k uncertainties below threshold (if configured)
        # This would require implementing uncertainty threshold checking
        
        return False
    
    def _print_resume_state(self) -> None:
        """Print detailed resume state table."""
        print("\n" + "="*60)
        print("RESUME STATE")
        print("="*60)
        
        # Runtime state table
        from prettytable import PrettyTable
        
        # Runtime statistics
        runtime_table = PrettyTable()
        runtime_table.field_names = ["Metric", "Value"]
        runtime_table.align["Metric"] = "l"
        runtime_table.align["Value"] = "r"
        
        runtime_table.add_row(["Evaluated Groups", f"{self.evaluated_groups:,}"])
        runtime_table.add_row(["Current Round", f"{self.current_round:,}"])
        runtime_table.add_row(["Total Evaluations", f"{self.total_evaluations:,}"])
        runtime_table.add_row(["Failed Evaluations", f"{self.failed_evaluations:,}"])
        runtime_table.add_row(["Success Rate", f"{(1 - self.failed_evaluations/max(1, self.total_evaluations))*100:.1f}%"])
        runtime_table.add_row(["Remaining Budget", f"{self.config.budget - self.evaluated_groups:,}"])
        
        print("Runtime Statistics:")
        print(runtime_table)
        
        # Current rankings
        print("\nCurrent Rankings (Top 10):")
        rankings_table = PrettyTable()
        rankings_table.field_names = ["Rank", "Crash ID", "Score (μ)", "Uncertainty (σ)", "Evals", "Win%"]
        rankings_table.align["Rank"] = "r"
        rankings_table.align["Score (μ)"] = "r"
        rankings_table.align["Uncertainty (σ)"] = "r"
        rankings_table.align["Evals"] = "r"
        rankings_table.align["Win%"] = "r"
        
        # Get all crashes and their scores
        crashes = list(self.fetcher.list_crashes())
        crash_scores = []
        
        for crash in crashes:
            score = self.ranker.get_score(crash.crash_id)
            uncertainty = self.ranker.get_uncertainty(crash.crash_id)
            eval_count = self.ranker.get_eval_count(crash.crash_id)
            win_pct = self.ranker.get_win_percentage(crash.crash_id)
            crash_scores.append((crash.crash_id, score, uncertainty, eval_count, win_pct))
        
        # Sort by score descending
        crash_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Show top 10
        for rank, (crash_id, score, uncertainty, eval_count, win_pct) in enumerate(crash_scores[:10], 1):
            rankings_table.add_row([
                rank,
                crash_id,
                f"{score:.3f}",
                f"{uncertainty:.3f}",
                eval_count,
                f"{win_pct:.1f}%"
            ])
        
        print(rankings_table)
        
        # Summary
        if self.evaluated_groups >= self.config.budget:
            print(f"\n✓ Tournament already completed ({self.evaluated_groups}/{self.config.budget} evaluations)")
        else:
            remaining = self.config.budget - self.evaluated_groups
            print(f"\n→ Resuming tournament with {remaining} evaluations remaining")
        
        print("="*60 + "\n")

    def _print_progress(self, phase: str, additional_info: str = "") -> None:
        """Print current progress with phase, budget, and convergence stats."""
        from prettytable import PrettyTable
        
        # Calculate progress metrics
        budget_progress = (self.evaluated_groups / self.config.budget) * 100
        remaining_budget = self.config.budget - self.evaluated_groups
        
        # Get convergence statistics
        crashes = list(self.fetcher.list_crashes())
        if not crashes:
            return
            
        scores = [self.ranker.get_score(crash.crash_id) for crash in crashes]
        uncertainties = [self.ranker.get_uncertainty(crash.crash_id) for crash in crashes]
        
        # Calculate convergence metrics
        score_range = max(scores) - min(scores) if len(scores) > 1 else 0
        avg_uncertainty = sum(uncertainties) / len(uncertainties)
        max_uncertainty = max(uncertainties)
        min_uncertainty = min(uncertainties)
        uncertainty_range = max_uncertainty - min_uncertainty
        
        # Top 3 and bottom 3 for context
        crash_scores = [(crash.crash_id, self.ranker.get_score(crash.crash_id)) for crash in crashes]
        crash_scores.sort(key=lambda x: x[1], reverse=True)
        top_3 = crash_scores[:3]
        bottom_3 = crash_scores[-3:]
        
        print(f"\n{'='*80}")
        print(f"PROGRESS UPDATE - {phase.upper()}")
        print(f"{'='*80}")
        
        # Main progress table
        progress_table = PrettyTable()
        progress_table.field_names = ["Metric", "Value", "Details"]
        progress_table.align["Metric"] = "l"
        progress_table.align["Value"] = "r"
        progress_table.align["Details"] = "l"
        
        progress_table.add_row([
            "Phase", 
            phase, 
            "Seed" if self.evaluated_groups < self.config.seed_groups else "Adaptive"
        ])
        progress_table.add_row([
            "Budget Progress", 
            f"{self.evaluated_groups}/{self.config.budget} ({budget_progress:.1f}%)",
            f"{remaining_budget} remaining"
        ])
        progress_table.add_row([
            "Current Round", 
            f"{self.current_round}",
            f"Groups per round: {self.config.groups_per_round}"
        ])
        progress_table.add_row([
            "Success Rate", 
            f"{(1 - self.failed_evaluations/max(1, self.total_evaluations))*100:.1f}%",
            f"{self.total_evaluations - self.failed_evaluations}/{self.total_evaluations} successful"
        ])
        
        print(progress_table)
        
        # Convergence statistics
        print(f"\nConvergence Statistics:")
        conv_table = PrettyTable()
        conv_table.field_names = ["Metric", "Value", "Interpretation"]
        conv_table.align["Metric"] = "l"
        conv_table.align["Value"] = "r"
        conv_table.align["Interpretation"] = "l"
        
        conv_table.add_row([
            "Score Range", 
            f"{score_range:.3f}",
            "Higher = more separation" if score_range > 5 else "Lower = more convergence"
        ])
        conv_table.add_row([
            "Avg Uncertainty", 
            f"{avg_uncertainty:.3f}",
            "Lower = more confident" if avg_uncertainty < 5 else "Higher = less confident"
        ])
        conv_table.add_row([
            "Uncertainty Range", 
            f"{uncertainty_range:.3f}",
            "Lower = more uniform confidence"
        ])
        conv_table.add_row([
            "Max Uncertainty", 
            f"{max_uncertainty:.3f}",
            "Target: < 3.0 for convergence"
        ])
        
        print(conv_table)
        
        # Top and bottom performers
        print(f"\nCurrent Rankings:")
        rank_table = PrettyTable()
        rank_table.field_names = ["Rank", "Crash ID", "Score", "Uncertainty", "Evals"]
        rank_table.align["Rank"] = "r"
        rank_table.align["Score"] = "r"
        rank_table.align["Uncertainty"] = "r"
        rank_table.align["Evals"] = "r"
        
        # Show top 3 and bottom 3
        for i, (crash_id, score) in enumerate(top_3, 1):
            uncertainty = self.ranker.get_uncertainty(crash_id)
            evals = self.ranker.get_eval_count(crash_id)
            rank_table.add_row([i, crash_id, f"{score:.3f}", f"{uncertainty:.3f}", evals])
        
        if len(crash_scores) > 6:
            rank_table.add_row(["...", "...", "...", "...", "..."])
            for i, (crash_id, score) in enumerate(bottom_3, len(crash_scores)-2):
                uncertainty = self.ranker.get_uncertainty(crash_id)
                evals = self.ranker.get_eval_count(crash_id)
                rank_table.add_row([i, crash_id, f"{score:.3f}", f"{uncertainty:.3f}", evals])
        elif len(crash_scores) > 3:
            for i, (crash_id, score) in enumerate(crash_scores[3:], 4):
                uncertainty = self.ranker.get_uncertainty(crash_id)
                evals = self.ranker.get_eval_count(crash_id)
                rank_table.add_row([i, crash_id, f"{score:.3f}", f"{uncertainty:.3f}", evals])
        
        print(rank_table)
        
        if additional_info:
            print(f"\n{additional_info}")
        
        print(f"{'='*80}\n")

    def _check_and_print_milestone(self) -> None:
        """Check if we've passed a milestone (multiple of 50) and print full rankings + recreate symlinks."""
        current_milestone = (self.evaluated_groups // 50) * 50
        
        # Check if we've crossed a milestone
        if current_milestone > self.last_milestone and current_milestone > 0:
            self.last_milestone = current_milestone
            
            print(f"\n{'='*80}")
            print(f"MILESTONE: {current_milestone} EVALUATIONS COMPLETED")
            print(f"{'='*80}\n")
            
            # Get all rankings
            rankings = self._get_final_rankings()
            
            # Print full rankings table
            from prettytable import PrettyTable
            table = PrettyTable()
            table.field_names = ["Rank", "Crash ID", "Score", "Uncertainty", "Evals", "Win%", "Avg Rank"]
            table.align["Rank"] = "r"
            table.align["Score"] = "r"
            table.align["Uncertainty"] = "r"
            table.align["Evals"] = "r"
            table.align["Win%"] = "r"
            table.align["Avg Rank"] = "r"
            
            for i, (crash_id, score) in enumerate(rankings.items(), 1):
                uncertainty = self.ranker.get_uncertainty(crash_id)
                eval_count = self.ranker.get_eval_count(crash_id)
                win_pct = self.ranker.get_win_percentage(crash_id)
                avg_rank = self.ranker.get_average_ranking(crash_id)
                table.add_row([
                    i, 
                    crash_id, 
                    f"{score:.3f}",
                    f"{uncertainty:.3f}",
                    eval_count,
                    f"{win_pct:.1f}%",
                    f"{avg_rank:.1f}"
                ])
            
            print("Full Rankings:")
            print(table)
            
            # Recreate ranked symlinks if output_dir is set
            if self.output_dir:
                self._recreate_ranked_directory(rankings)
            
            print(f"{'='*80}\n")
    
    def _recreate_ranked_directory(self, rankings: Dict[str, float]) -> None:
        """Recreate ranked directory with symlinks."""
        from pathlib import Path
        import shutil
        
        ranked_dir = self.output_dir / "ranked"
        
        # Clear existing directory
        if ranked_dir.exists():
            shutil.rmtree(ranked_dir)
            self.logger.info(f"Cleared existing ranked directory for milestone update")
        
        # Create fresh directory
        ranked_dir.mkdir(exist_ok=True)
        
        # Create symlinks
        for rank, (crash_id, score) in enumerate(rankings.items(), 1):
            crash = self.fetcher.get_crash(crash_id)
            symlink_name = f"{rank}_{crash_id}"
            symlink_path = ranked_dir / symlink_name
            crash_file_path = Path(crash.file_path).resolve()
            symlink_path.symlink_to(crash_file_path)
        
        self.logger.info(f"Recreated {len(rankings)} ranked symlinks at milestone {self.last_milestone}")
        print(f"✓ Recreated ranked directory with {len(rankings)} symlinks: {ranked_dir}")

    def run(self) -> Dict[str, float]:
        """
        Run the complete evaluation process.
        
        Load snapshot if exists, execute seed phase, loop uncertainty rounds.
        """
        self.logger.info(f"Starting crash tournament with config: {self.config}")
        print(f"Starting crash tournament with config: {self.config}")
        
        
        # Load snapshot if exists (idempotent restart)
        snapshot = self.storage.load_snapshot()
        if snapshot:
            self.logger.info("Loading existing snapshot")
            print("Loading existing snapshot...")
            
            # Handle both old (flat) and new (nested) snapshot formats
            if 'ranker_state' in snapshot:
                # New format
                self.ranker.load_snapshot(snapshot['ranker_state'])
                runtime_state = snapshot.get('runtime_state', {})
                self.evaluated_groups = runtime_state.get('evaluated_groups', 0)
                self.current_round = runtime_state.get('current_round', 0)
                self.total_evaluations = runtime_state.get('total_evaluations', 0)
                self.failed_evaluations = runtime_state.get('failed_evaluations', 0)
                self.last_milestone = runtime_state.get('last_milestone', 0)
            else:
                # Old format (backwards compatibility)
                self.ranker.load_snapshot(snapshot)
            
            # Print detailed resume state
            self._print_resume_state()
        
        # Seed phase
        self.logger.info("Running seed phase")
        print("Running seed phase...")
        seed_groups = self._seed_phase()
        self._evaluate_groups(seed_groups)
        
        # Show progress after seed phase
        self._print_progress("Seed Phase Complete", "Initial random evaluations completed")
        
        # Uncertainty rounds
        self.logger.info("Running uncertainty rounds")
        print("Running uncertainty rounds...")
        while not self._check_stopping_conditions():
            self.current_round += 1
            self.logger.info(f"Starting round {self.current_round}")
            print(f"Round {self.current_round}...")
            
            results = self._uncertainty_round()
            if not results:
                self.logger.info("No more groups to evaluate")
                print("No more groups to evaluate")
                break
            
            self.logger.info(f"Round {self.current_round} completed: {len(results)} groups (total: {self.evaluated_groups})")
            print(f"  Evaluated {len(results)} groups (total: {self.evaluated_groups})")
            
            # Show progress after each round
            phase = "Adaptive Round" if self.evaluated_groups >= self.config.seed_groups else "Seed Phase"
            self._print_progress(phase, f"Round {self.current_round} completed with {len(results)} evaluations")
        
        # Return final rankings
        self.logger.info("Tournament complete!")
        print("Tournament complete!")
        
        # Show final progress summary
        self._print_progress("Tournament Complete", "All evaluations finished - final rankings generated")
        
        return self._get_final_rankings()
    
    def _get_top_scores(self, n: int = 5) -> List[tuple]:
        """Get top N crash scores for logging."""
        crashes = list(self.fetcher.list_crashes())
        scores = []
        
        for crash in crashes:
            score = self.ranker.get_score(crash.crash_id)
            uncertainty = self.ranker.get_uncertainty(crash.crash_id)
            scores.append((crash.crash_id, score, uncertainty))
        
        # Sort by score (mu) descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:n]
    
    def _get_final_rankings(self) -> Dict[str, float]:
        """Get final crash rankings."""
        crashes = list(self.fetcher.list_crashes())
        rankings = {}
        
        for crash in crashes:
            score = self.ranker.get_score(crash.crash_id)
            rankings[crash.crash_id] = score
        
        # Sort by score (highest first)
        return dict(sorted(rankings.items(), key=lambda x: x[1], reverse=True))
