"""
Simulated judge implementation.

Samples k-way orderings from latent scores with noise parameter for testing.
"""

import random
from typing import Dict, List, Sequence

from ..interfaces import Judge
from ..models import Crash, OrdinalResult


class SimulatedJudge(Judge):
    """
    Simulated judge for testing purposes.
    
    Samples k-way orderings from ground truth scores with added noise.
    """
    
    def __init__(self, ground_truth: Dict[str, float], noise: float = 0.1):
        """
        Initialize simulated judge.
        
        Args:
            ground_truth: Dict mapping crash_id to true exploitability score
            noise: Amount of noise to add (0-1, where 1 = full noise)
        """
        self.ground_truth = ground_truth
        self.noise = max(0.0, min(1.0, noise))  # Clamp to [0, 1]
        self.judge_id = "simulated"
    
    def _add_noise(self, score: float) -> float:
        """Add Gaussian noise to score."""
        if self.noise == 0:
            return score
        
        # Scale noise by score magnitude
        noise_scale = abs(score) * self.noise
        noise = random.gauss(0, noise_scale)
        return score + noise
    
    def _get_noisy_scores(self, crashes: Sequence[Crash]) -> List[tuple[Crash, float]]:
        """Get noisy scores for crashes."""
        noisy_scores = []
        
        for crash in crashes:
            # Get ground truth score
            true_score = self.ground_truth.get(crash.crash_id, 0.0)
            
            # Add noise
            noisy_score = self._add_noise(true_score)
            
            noisy_scores.append((crash, noisy_score))
        
        return noisy_scores
    
    def evaluate_group(self, crashes: Sequence[Crash], *, grading: bool = False) -> OrdinalResult:
        """
        Evaluate group of crashes using simulated ground truth + noise.
        
        Args:
            crashes: Sequence of crashes to evaluate
            grading: Ignored for simulated judge
            
        Returns:
            OrdinalResult with ordered crash IDs
        """
        if not crashes:
            raise ValueError("Cannot evaluate empty group")
        
        # Get noisy scores
        noisy_scores = self._get_noisy_scores(crashes)
        
        # Sort by noisy scores (descending - highest exploitability first)
        noisy_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Extract ordered crash IDs
        ordered_ids = [crash.crash_id for crash, _ in noisy_scores]
        
        # Generate rationale for top choice
        top_crash = noisy_scores[0][0]
        top_score = noisy_scores[0][1]
        rationale_top = f"Simulated evaluation: {top_crash.crash_id} scored {top_score:.3f} (ground truth: {self.ground_truth.get(top_crash.crash_id, 0.0):.3f})"
        
        # Generate raw output
        raw_output = f"Simulated judge evaluation:\n"
        for i, (crash, score) in enumerate(noisy_scores):
            true_score = self.ground_truth.get(crash.crash_id, 0.0)
            raw_output += f"{i+1}. {crash.crash_id}: {score:.3f} (true: {true_score:.3f})\n"
        
        return OrdinalResult(
            ordered_ids=ordered_ids,
            raw_output=raw_output,
            parsed_result={"rationale_top": rationale_top},
            judge_id=self.judge_id,
            group_size=len(crashes),
        )
    
    def get_ground_truth(self) -> Dict[str, float]:
        """Get ground truth scores for debugging."""
        return self.ground_truth.copy()
    
    def set_noise(self, noise: float) -> None:
        """Update noise level."""
        self.noise = max(0.0, min(1.0, noise))
    
    def get_noise(self) -> float:
        """Get current noise level."""
        return self.noise