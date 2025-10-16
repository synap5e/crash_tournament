"""
Uncertainty selector implementation.

Implements uncertainty-based sampling for active learning.
"""

import random
import numpy as np
from typing import Dict, List, Optional, Sequence

from ..interfaces import Ranker, Selector


class UncertaintySelector(Selector):
    """
    Uncertainty-based selector for active learning.
    
    Selects groups by focusing on high-uncertainty crashes and
    sampling nearby crashes for informative comparisons.
    """
    
    def __init__(
        self,
        ranker: Ranker,
        K_uncertain: Optional[int] = None,
        delta_mu: float = 1.0,
        max_evals_per_crash: Optional[int] = None,
        temperature: float = 1.0,
    ):
        """
        Initialize uncertainty selector.
        
        Args:
            ranker: Ranker instance for querying mu/sigma
            K_uncertain: Number of uncertain candidates to consider (default: 5*k)
            delta_mu: Maximum mu difference for nearby crashes
            max_evals_per_crash: Maximum evaluations per crash (None = unlimited)
            temperature: Temperature parameter for probabilistic sampling (T=1.0 = proportional to σ, T<1.0 = more greedy, T>1.0 = more diverse)
        """
        self.ranker = ranker
        self.delta_mu = delta_mu
        self.max_evals_per_crash = max_evals_per_crash
        self.temperature = temperature
        
        # Track evaluation counts per crash
        self.eval_counts: Dict[str, int] = {}
        
        # Store K_uncertain for later use
        self._K_uncertain = K_uncertain
        
        # Setup logger
        from ..logging_config import get_logger
        self.logger = get_logger("uncertainty_selector")
    
    def _get_uncertainty_scores(self, crash_ids: List[str]) -> List[tuple[str, float]]:
        """Get uncertainty scores for all crashes."""
        scores = []
        for crash_id in crash_ids:
            uncertainty = self.ranker.get_uncertainty(crash_id)
            scores.append((crash_id, uncertainty))
        return scores
    
    def _probabilistic_sample_uncertain_crashes(self, uncertainty_scores: List[tuple[str, float]], k: int) -> List[str]:
        """
        Sample crashes probabilistically based on uncertainty scores.
        
        Uses temperature-scaled softmax: p_i = (σ_i)^(1/T) / Σ_j (σ_j)^(1/T)
        
        Args:
            uncertainty_scores: List of (crash_id, sigma) tuples
            k: Number of crashes to sample
            
        Returns:
            List of sampled crash IDs
        """
        if not uncertainty_scores:
            return []
        
        # Extract sigma values
        sigmas = np.array([score for _, score in uncertainty_scores])
        
        # Apply temperature scaling: σ^(1/T)
        if self.temperature > 0:
            scaled_sigmas = np.power(sigmas, 1.0 / self.temperature)
        else:
            # Handle T=0 case (pure greedy)
            scaled_sigmas = np.zeros_like(sigmas)
            max_idx = np.argmax(sigmas)
            scaled_sigmas[max_idx] = 1.0
        
        # Convert to probabilities (softmax)
        if np.sum(scaled_sigmas) > 0:
            probabilities = scaled_sigmas / np.sum(scaled_sigmas)
        else:
            # Fallback to uniform if all sigmas are zero
            probabilities = np.ones_like(scaled_sigmas) / len(scaled_sigmas)
        
        # Sample k crashes without replacement
        crash_ids = [crash_id for crash_id, _ in uncertainty_scores]
        k = min(k, len(crash_ids))
        
        if k == len(crash_ids):
            return crash_ids
        
        # Use numpy's choice for weighted sampling without replacement
        try:
            sampled_indices = np.random.choice(
                len(crash_ids), 
                size=k, 
                replace=False, 
                p=probabilities
            )
            return [crash_ids[i] for i in sampled_indices]
        except ValueError:
            # Fallback to uniform sampling if probabilities are invalid
            return random.sample(crash_ids, k)
    
    def _get_nearby_crashes(self, target_crash_id: str, all_crash_ids: List[str], k: int) -> List[str]:
        """Get crashes with mu near target crash's mu."""
        target_mu = self.ranker.get_score(target_crash_id)
        nearby_crashes = []
        
        for crash_id in all_crash_ids:
            if crash_id == target_crash_id:
                continue
            
            mu = self.ranker.get_score(crash_id)
            if abs(mu - target_mu) <= self.delta_mu:
                nearby_crashes.append(crash_id)
        
        # Sample up to k-1 nearby crashes
        return random.sample(nearby_crashes, min(k - 1, len(nearby_crashes)))
    
    def _is_crash_over_evaluated(self, crash_id: str) -> bool:
        """Check if crash has been evaluated too many times."""
        if self.max_evals_per_crash is None:
            return False
        return self.eval_counts.get(crash_id, 0) >= self.max_evals_per_crash
    
    def _update_eval_counts(self, group: List[str]) -> None:
        """Update evaluation counts for crashes in group."""
        for crash_id in group:
            self.eval_counts[crash_id] = self.eval_counts.get(crash_id, 0) + 1
    
    def _generate_unique_group(self, uncertain_candidates: List[str], all_crash_ids: List[str], k: int) -> Optional[List[str]]:
        """Generate a unique group avoiding over-evaluated crashes."""
        # Filter out over-evaluated crashes
        available_candidates = [
            crash_id for crash_id in uncertain_candidates
            if not self._is_crash_over_evaluated(crash_id)
        ]
        
        if not available_candidates:
            # If no uncertain candidates available, use any available crashes
            available_candidates = [
                crash_id for crash_id in all_crash_ids
                if not self._is_crash_over_evaluated(crash_id)
            ]
        
        if not available_candidates:
            return None
        
        # Select from available candidates (prioritizing uncertain ones if available)
        if available_candidates:
            target_crash = available_candidates[0]
        else:
            return None
        
        # Get nearby crashes (excluding over-evaluated ones)
        nearby_crashes = self._get_nearby_crashes(target_crash, all_crash_ids, k)
        nearby_crashes = [c for c in nearby_crashes if not self._is_crash_over_evaluated(c)]
        
        # Build group
        group = [target_crash]
        group.extend(nearby_crashes[:k-1])  # Take up to k-1 nearby crashes
        
        # Log group selection details
        target_uncertainty = self.ranker.get_uncertainty(target_crash)
        self.logger.info(f"Selected group: {group}")
        self.logger.info(f"  Target crash: {target_crash} (σ: {target_uncertainty:.2f})")
        self.logger.info(f"  Nearby crashes: {nearby_crashes[:k-1]}")
        
        # Fill with random crashes if needed
        if len(group) < k:
            remaining_crashes = [
                c for c in all_crash_ids 
                if c not in group and not self._is_crash_over_evaluated(c)
            ]
            needed = k - len(group)
            if remaining_crashes:
                group.extend(random.sample(remaining_crashes, min(needed, len(remaining_crashes))))
        
        # Return group even if smaller than k (handles insufficient crashes case)
        return group if len(group) >= 2 else None  # Need at least 2 for comparison
    
    def next_groups(self, all_crash_ids: Sequence[str], k: int, budget: int) -> Sequence[Sequence[str]]:
        """
        Return list of crash ID groups to evaluate based on uncertainty.
        
        Args:
            all_crash_ids: All available crash IDs to select from
            k: Group size
            budget: Number of groups to return
            
        Implements uncertainty-based sampling algorithm:
        1. Get mu/sigma for all crashes, compute uncertainty score u = sigma
        2. Select top K_uncertain candidates
        3. For each group: sample 1 highest-uncertainty item, fill remaining k-1 items
           by sampling crashes with mu near selected item (within delta_mu)
        4. Ensure group uniqueness and limited overlap
        """
        if not all_crash_ids:
            return []
        
        # Determine K_uncertain (default: 5*k groups worth)
        K_uncertain = self._K_uncertain or (5 * k)
        
        # Get uncertainty scores for all crashes
        uncertainty_scores = self._get_uncertainty_scores(all_crash_ids)
        
        # Sample K_uncertain crashes probabilistically based on uncertainty
        uncertain_candidates = self._probabilistic_sample_uncertain_crashes(uncertainty_scores, K_uncertain)
        
        # Log sampling details
        if uncertain_candidates:
            self.logger.info(f"Probabilistic sampling (T={self.temperature}): selected {len(uncertain_candidates)} candidates")
            for i, crash_id in enumerate(uncertain_candidates[:5]):  # Log first 5
                sigma = self.ranker.get_uncertainty(crash_id)
                self.logger.info(f"  {i+1}. {crash_id}: σ={sigma:.3f}")
            if len(uncertain_candidates) > 5:
                self.logger.info(f"  ... and {len(uncertain_candidates) - 5} more")
        
        groups = []
        seen_groups = set()
        for _ in range(budget):
            group = self._generate_unique_group(uncertain_candidates, all_crash_ids, k)
            if group is None:
                break  # No more valid groups possible
            
            # Check for duplicates using normalized group (sorted)
            normalized_group = tuple(sorted(group))
            if normalized_group not in seen_groups:
                groups.append(group)
                seen_groups.add(normalized_group)
                self._update_eval_counts(group)
            else:
                # Try a few more times to find unique group
                for _ in range(3):
                    group = self._generate_unique_group(uncertain_candidates, all_crash_ids, k)
                    if group is not None:
                        normalized_group = tuple(sorted(group))
                        if normalized_group not in seen_groups:
                            groups.append(group)
                            seen_groups.add(normalized_group)
                            self._update_eval_counts(group)
                            break
                else:
                    break  # No more unique groups possible
        
        return groups
    
    
    def get_eval_counts(self) -> Dict[str, int]:
        """Get evaluation counts for debugging."""
        return self.eval_counts.copy()
    
    def reset_eval_counts(self) -> None:
        """Reset evaluation counts (for testing)."""
        self.eval_counts.clear()