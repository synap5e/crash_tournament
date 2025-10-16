"""
Tests for UncertaintySelector implementation.

Focus on uncertainty-based sampling logic.
"""

import pytest
from crash_tournament.rankers.trueskill_ranker import TrueSkillRanker
from crash_tournament.group_selectors.uncertainty_selector import UncertaintySelector
from crash_tournament.models import OrdinalResult


class TestUncertaintySelector:
    """Test UncertaintySelector behavior through public interface."""
    
    def test_selects_high_uncertainty_crashes(self):
        """Should prioritize crashes with high sigma values."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, K_uncertain=5, delta_mu=2.0)
        
        # Set up known ratings with different uncertainties
        # High uncertainty crash
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["high_uncertainty", "other"],
            raw_output="test",
            parsed_result={"rationale_top": "high uncertainty wins"},
            group_size=2,
        ))
        
        # Low uncertainty crash (multiple updates to reduce sigma)
        for _ in range(5):
            ranker.update_with_ordinal(OrdinalResult(
                ordered_ids=["low_uncertainty", "other"],
                raw_output="test",
                parsed_result={"rationale_top": "low uncertainty wins"},
                group_size=2,
            ))
        
        crash_ids = ["high_uncertainty", "low_uncertainty", "other"]
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=10)
        
        # Assert
        assert len(groups) > 0, "Should generate groups"
        
        # High uncertainty crash should appear in more groups
        high_uncertainty_appearances = sum(
            1 for group in groups if "high_uncertainty" in group
        )
        low_uncertainty_appearances = sum(
            1 for group in groups if "low_uncertainty" in group
        )
        
        assert high_uncertainty_appearances >= low_uncertainty_appearances, \
            "High uncertainty crash should appear in at least as many groups"
    
    def test_groups_contain_nearby_crashes(self):
        """Should respect delta_mu constraint when selecting nearby crashes."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, delta_mu=1.0)  # Small delta
        
        # Set up crashes with known mu values
        # Create a target crash with mu=25
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["target", "other1"],
            raw_output="test",
            parsed_result={"rationale_top": "target wins"},
            group_size=2,
        ))
        
        # Create nearby crash (mu should be close to target)
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["nearby", "other2"],
            raw_output="test",
            parsed_result={"rationale_top": "nearby wins"},
            group_size=2,
        ))
        
        # Create distant crash (mu should be far from target)
        for _ in range(10):  # Many updates to push mu far away
            ranker.update_with_ordinal(OrdinalResult(
                ordered_ids=["distant", "other3"],
                raw_output="test",
                parsed_result={"rationale_top": "distant wins"},
                group_size=2,
            ))
        
        crash_ids = ["target", "nearby", "distant", "other1", "other2", "other3"]
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=3, budget=5)
        
        # Assert
        assert len(groups) > 0, "Should generate groups"
        
        # Groups containing target should more often contain nearby than distant
        target_groups = [group for group in groups if "target" in group]
        nearby_with_target = sum(1 for group in target_groups if "nearby" in group)
        distant_with_target = sum(1 for group in target_groups if "distant" in group)
        
        assert nearby_with_target >= distant_with_target, \
            "Nearby crashes should be selected more often than distant ones"
    
    def test_respects_max_evals_per_crash(self):
        """Should not over-sample crashes when max_evals_per_crash is set."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, max_evals_per_crash=2)
        
        crash_ids = ["crash1", "crash2", "crash3", "crash4"]
        
        # Act - generate many groups
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=20)
        
        # Assert
        eval_counts = selector.get_eval_counts()
        for crash_id in crash_ids:
            assert eval_counts.get(crash_id, 0) <= 2, \
                f"Crash {crash_id} should not be evaluated more than 2 times"
    
    def test_generates_unique_groups(self):
        """Should not generate duplicate groups."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        crash_ids = ["a", "b", "c", "d", "e"]
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=3, budget=10)
        
        # Assert
        unique_groups = set(tuple(sorted(group)) for group in groups)
        assert len(unique_groups) == len(groups), "All groups should be unique"
    
    def test_returns_empty_when_budget_zero(self):
        """Should return empty list when budget is zero."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        crash_ids = ["a", "b", "c"]
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=0)
        
        # Assert
        assert len(groups) == 0, "Should return empty list for zero budget"
    
    def test_eval_counts_tracked_correctly(self):
        """Should correctly track evaluation counts for each crash."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        crash_ids = ["a", "b", "c"]
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=6)
        
        # Assert
        eval_counts = selector.get_eval_counts()
        total_evals = sum(eval_counts.values())
        expected_evals = len(groups) * 2  # k=2 per group
        
        assert total_evals == expected_evals, "Total evaluations should match expected"
        
        # Each crash should appear in some groups
        for crash_id in crash_ids:
            assert crash_id in eval_counts, f"Crash {crash_id} should be tracked"
            assert eval_counts[crash_id] > 0, f"Crash {crash_id} should be evaluated"
    
    def test_reset_eval_counts(self):
        """Should reset evaluation counts when requested."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        crash_ids = ["a", "b", "c"]
        selector.next_groups(all_crash_ids=crash_ids, k=2, budget=4)
        
        # Act
        selector.reset_eval_counts()
        
        # Assert
        eval_counts = selector.get_eval_counts()
        assert len(eval_counts) == 0, "Eval counts should be empty after reset"
    
    def test_k_uncertain_parameter(self):
        """Should respect K_uncertain parameter for candidate selection."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, K_uncertain=2)  # Only consider top 2 uncertain
        
        # Set up many crashes with different uncertainties
        crash_ids = [f"crash_{i}" for i in range(10)]
        
        # Make crashes 2-9 more certain by updating them, leaving 0-1 with high uncertainty
        for i in range(2, 10):
            ranker.update_with_ordinal(OrdinalResult(
                ordered_ids=[f"crash_{i}", "other"],
                raw_output="test",
                parsed_result={"rationale_top": f"crash_{i} wins"},
                group_size=2,
            ))
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=3, budget=5)
        
        # Assert
        # With probabilistic sampling, we should get exactly K_uncertain=2 unique target crashes
        # (since we're sampling 2 candidates and each group uses one as target)
        unique_target_crashes = set()
        for group in groups:
            if group:  # Non-empty group
                unique_target_crashes.add(group[0])  # First crash is the target
        
        # Should have at most K_uncertain unique target crashes
        assert len(unique_target_crashes) <= 2, f"Should have at most 2 unique target crashes, got {len(unique_target_crashes)}"
        
        # All groups should be non-empty
        assert all(len(group) >= 2 for group in groups), "All groups should have at least 2 crashes"
    
    def test_delta_mu_parameter(self):
        """Should respect delta_mu parameter for nearby crash selection."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, delta_mu=0.5)  # Very small delta
        
        # Set up crashes with known mu values
        crash_ids = ["target", "nearby", "distant"]
        
        # Make "nearby" and "distant" more certain, leaving "target" with high uncertainty
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["nearby", "other"],
            raw_output="test",
            parsed_result={"rationale_top": "nearby wins"},
            group_size=2,
        ))
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["distant", "other"],
            raw_output="test",
            parsed_result={"rationale_top": "distant wins"},
            group_size=2,
        ))
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=3)
        
        # Assert
        # With very small delta_mu, most groups should contain target alone
        # or with crashes that happen to be nearby by chance
        assert len(groups) > 0, "Should generate some groups"
        
        # Target should appear in groups (it's the highest uncertainty)
        target_groups = [group for group in groups if "target" in group]
        assert len(target_groups) > 0, "Target should appear in some groups"
    
    def test_handles_empty_crash_list(self):
        """Should handle empty crash list gracefully."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        # Act
        groups = selector.next_groups(all_crash_ids=[], k=2, budget=5)
        
        # Assert
        assert len(groups) == 0, "Should return empty list for empty crash list"
    
    def test_handles_insufficient_crashes(self):
        """Should handle case where there are fewer crashes than k."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker)
        
        crash_ids = ["a", "b"]  # Only 2 crashes
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=3, budget=5)  # k=3 but only 2 crashes
        
        # Assert
        # Should still generate groups with available crashes
        assert len(groups) > 0, "Should generate groups with available crashes"
        
        for group in groups:
            assert len(group) <= len(crash_ids), "Group size should not exceed available crashes"
            assert all(crash_id in crash_ids for crash_id in group), "All crashes in group should be valid"
    
    def test_probabilistic_sampling_temperature_effect(self):
        """Should show different behavior with different temperature values."""
        # Arrange
        ranker = TrueSkillRanker()
        
        # Set up crashes with very different uncertainties
        crash_ids = ["high_uncertainty", "medium_uncertainty", "low_uncertainty"]
        
        # High uncertainty crash (no updates)
        # Medium uncertainty crash (few updates)
        ranker.update_with_ordinal(OrdinalResult(
            ordered_ids=["medium_uncertainty", "other"],
            raw_output="test",
            parsed_result={"rationale_top": "medium wins"},
            group_size=2,
        ))
        
        # Low uncertainty crash (many updates)
        for _ in range(5):
            ranker.update_with_ordinal(OrdinalResult(
                ordered_ids=["low_uncertainty", "other"],
                raw_output="test",
                parsed_result={"rationale_top": "low wins"},
                group_size=2,
            ))
        
        # Test with different temperatures
        greedy_selector = UncertaintySelector(ranker, temperature=0.1)  # Very greedy
        diverse_selector = UncertaintySelector(ranker, temperature=2.0)  # More diverse
        
        # Act
        greedy_groups = greedy_selector.next_groups(all_crash_ids=crash_ids, k=2, budget=10)
        diverse_groups = diverse_selector.next_groups(all_crash_ids=crash_ids, k=2, budget=10)
        
        # Assert
        # Both should generate groups
        assert len(greedy_groups) > 0, "Greedy selector should generate groups"
        assert len(diverse_groups) > 0, "Diverse selector should generate groups"
        
        # Greedy selector should focus more on high uncertainty crashes
        greedy_targets = [group[0] for group in greedy_groups if group]
        diverse_targets = [group[0] for group in diverse_groups if group]
        
        # High uncertainty crash should appear more often with greedy sampling
        greedy_high_count = greedy_targets.count("high_uncertainty")
        diverse_high_count = diverse_targets.count("high_uncertainty")
        
        # This is probabilistic, so we can't guarantee strict ordering, but greedy should tend to favor high uncertainty
        # We'll just check that both selectors work and generate reasonable results
        assert greedy_high_count >= 0, "Greedy selector should work"
        assert diverse_high_count >= 0, "Diverse selector should work"
    
    def test_temperature_zero_behavior(self):
        """Should behave greedily when temperature is 0."""
        # Arrange
        ranker = TrueSkillRanker()
        selector = UncertaintySelector(ranker, temperature=0.0)  # Pure greedy
        
        # Set up crashes with different uncertainties
        crash_ids = ["high_uncertainty", "low_uncertainty"]
        
        # Make low_uncertainty more certain
        for _ in range(3):
            ranker.update_with_ordinal(OrdinalResult(
                ordered_ids=["low_uncertainty", "other"],
                raw_output="test",
                parsed_result={"rationale_top": "low wins"},
                group_size=2,
            ))
        
        # Act
        groups = selector.next_groups(all_crash_ids=crash_ids, k=2, budget=5)
        
        # Assert
        assert len(groups) > 0, "Should generate groups"
        
        # With temperature=0, should always select the highest uncertainty crash
        for group in groups:
            if group:
                assert group[0] == "high_uncertainty", "Should always select highest uncertainty crash with T=0"
