#!/usr/bin/env python3
"""Test script to verify deterministic tie-breaking behavior."""

import numpy as np
from crash_tournament.group_selectors.uncertainty_selector import UncertaintySelector
from crash_tournament.rankers.trueskill_ranker import TrueSkillRanker

def test_tie_breaking():
    """Test that T=0 behavior is deterministic for equal sigma values."""
    ranker = TrueSkillRanker()
    selector = UncertaintySelector(ranker, temperature=0.0)
    
    # Create crashes with identical sigma values
    crash_ids = ["crash_1", "crash_2", "crash_3", "crash_4", "crash_5"]
    
    # Set all crashes to have the same sigma value
    from crash_tournament.models import OrdinalResult
    for crash_id in crash_ids:
        result = OrdinalResult(
            ordered_ids=[crash_id, "other_crash"],
            raw_output="",
            parsed_result={},
            timestamp=0.0,
            judge_id="test",
            group_size=2
        )
        ranker.update_with_ordinal(result)
    
    # Test multiple times to ensure deterministic behavior
    results = []
    for _ in range(10):
        uncertainty_scores = [(crash_id, ranker.get_uncertainty(crash_id)) for crash_id in crash_ids]
        sampled = selector._probabilistic_sample_uncertain_crashes(uncertainty_scores, 1)
        results.append(sampled[0] if sampled else None)
    
    # All results should be the same (deterministic)
    print(f"Tie-breaking test results: {results}")
    print(f"All results identical: {len(set(results)) == 1}")
    print(f"First crash selected: {results[0]}")
    
    # Clean up
    import os
    os.remove("test_tie_breaking.py")

if __name__ == "__main__":
    test_tie_breaking()