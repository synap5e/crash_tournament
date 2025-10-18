"""
Tests for SimulatedJudge implementation.

Focus on ground truth + noise behavior.
"""

import pytest
from crash_tournament.judges.sim_judge import SimulatedJudge
from crash_tournament.models import Crash


class TestSimulatedJudge:
    """Test SimulatedJudge behavior through public interface."""
    
    def test_zero_noise_perfect_ordering(self):
        """With noise=0, should return exact ground truth order."""
        # Arrange
        ground_truth = {
            "crash_a": 10.0,  # Highest score
            "crash_b": 5.0,   # Middle score
            "crash_c": 1.0,   # Lowest score
        }
        judge = SimulatedJudge(ground_truth, noise=0.0)
        
        crashes = [
            Crash(crash_id="crash_a", file_path="crash_a.json"),
            Crash(crash_id="crash_b", file_path="crash_b.json"),
            Crash(crash_id="crash_c", file_path="crash_c.json"),
        ]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        assert result.ordered_ids == ["crash_a", "crash_b", "crash_c"], \
            "Should return exact ground truth order with zero noise"
        assert len(result.ordered_ids) == 3
        assert result.judge_id == "simulated"
    
    def test_noise_adds_variance(self):
        """With noise>0, should produce different orderings over multiple runs."""
        # Arrange
        ground_truth = {
            "crash_a": 5.0,
            "crash_b": 4.0,
            "crash_c": 3.0,
        }
        judge = SimulatedJudge(ground_truth, noise=0.5)  # High noise
        
        crashes = [
            Crash(crash_id="crash_a", file_path="crash_a.json"),
            Crash(crash_id="crash_b", file_path="crash_b.json"),
            Crash(crash_id="crash_c", file_path="crash_c.json"),
        ]
        
        # Act - run multiple times
        results = []
        for _ in range(10):
            result = judge.evaluate_group(crashes)
            results.append(result.ordered_ids)
        
        # Assert
        # Should get some variation in ordering
        unique_orderings = set(tuple(ordering) for ordering in results)
        assert len(unique_orderings) > 1, "Should produce different orderings with noise"
        
        # All results should contain all crashes
        for result in results:
            assert set(result) == {"crash_a", "crash_b", "crash_c"}, \
                "All crashes should be present in each result"
    
    def test_result_contains_all_crashes(self):
        """Result should contain all input crashes."""
        # Arrange
        ground_truth = {"crash_x": 1.0, "crash_y": 2.0, "crash_z": 3.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        crashes = [
            Crash(crash_id="crash_x", file_path="crash_x.json"),
            Crash(crash_id="crash_y", file_path="crash_y.json"),
            Crash(crash_id="crash_z", file_path="crash_z.json"),
        ]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        assert len(result.ordered_ids) == 3, "Should contain all 3 crashes"
        assert set(result.ordered_ids) == {"crash_x", "crash_y", "crash_z"}, \
            "Should contain all input crash IDs"
    
    def test_result_is_ordinalresult(self):
        """Should return OrdinalResult type."""
        # Arrange
        ground_truth = {"crash_1": 1.0, "crash_2": 2.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        crashes = [
            Crash(crash_id="crash_1", file_path="crash_1.json"),
            Crash(crash_id="crash_2", file_path="crash_2.json"),
        ]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        from crash_tournament.models import OrdinalResult
        assert isinstance(result, OrdinalResult), "Should return OrdinalResult instance"
        assert result.judge_id == "simulated"
        assert len(result.ordered_ids) == 2
    
    def test_rationale_includes_scores(self):
        """Output should be informative and include score information."""
        # Arrange
        ground_truth = {"crash_high": 10.0, "crash_low": 1.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        crashes = [
            Crash(crash_id="crash_high", file_path="crash_high.json"),
            Crash(crash_id="crash_low", file_path="crash_low.json"),
        ]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        assert "crash_high" in result.parsed_result["rationale_top"], "Rationale should mention crash IDs"
        assert "10.0" in result.parsed_result["rationale_top"], "Rationale should include ground truth score"
        assert "Simulated evaluation" in result.parsed_result["rationale_top"], "Should indicate simulated evaluation"
        
        # Raw output should be informative
        assert "crash_high" in result.raw_output, "Raw output should include crash IDs"
        assert "10.0" in result.raw_output, "Raw output should include scores"
        assert "true:" in result.raw_output, "Raw output should include ground truth"
    
    def test_handles_missing_ground_truth(self):
        """Should handle crashes not in ground truth gracefully."""
        # Arrange
        ground_truth = {"crash_a": 5.0}  # Only one crash in ground truth
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        crashes = [
            Crash(crash_id="crash_a", file_path="crash_a.json"),
            Crash(crash_id="crash_b", file_path="crash_b.json"),  # Not in ground truth
        ]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        assert len(result.ordered_ids) == 2, "Should handle all crashes"
        assert "crash_a" in result.ordered_ids, "Known crash should be included"
        assert "crash_b" in result.ordered_ids, "Unknown crash should be included"
    
    def test_noise_parameter_affects_variance(self):
        """Higher noise should produce more variance."""
        # Arrange
        ground_truth = {"crash_a": 5.0, "crash_b": 4.0, "crash_c": 3.0}
        
        crashes = [
            Crash(crash_id="crash_a", file_path="crash_a.json"),
            Crash(crash_id="crash_b", file_path="crash_b.json"),
            Crash(crash_id="crash_c", file_path="crash_c.json"),
        ]
        
        # Act - test with different noise levels
        judge_low_noise = SimulatedJudge(ground_truth, noise=0.1)
        judge_high_noise = SimulatedJudge(ground_truth, noise=0.9)
        
        # Run multiple times with each noise level
        low_noise_results = []
        high_noise_results = []
        
        for _ in range(20):
            low_result = judge_low_noise.evaluate_group(crashes)
            high_result = judge_high_noise.evaluate_group(crashes)
            
            low_noise_results.append(tuple(low_result.ordered_ids))
            high_noise_results.append(tuple(high_result.ordered_ids))
        
        # Assert
        low_noise_unique = len(set(low_noise_results))
        high_noise_unique = len(set(high_noise_results))
        
        assert high_noise_unique >= low_noise_unique, \
            "Higher noise should produce at least as much variance"
    
    def test_get_ground_truth(self):
        """Should return ground truth for debugging."""
        # Arrange
        ground_truth = {"crash_1": 1.0, "crash_2": 2.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        # Act
        retrieved_truth = judge.get_ground_truth()
        
        # Assert
        assert retrieved_truth == ground_truth, "Should return exact ground truth"
        assert retrieved_truth is not ground_truth, "Should return copy, not reference"
    
    def test_set_noise(self):
        """Should allow updating noise level."""
        # Arrange
        ground_truth = {"crash_a": 5.0, "crash_b": 4.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        # Act
        judge.set_noise(0.5)
        
        # Assert
        assert judge.get_noise() == 0.5, "Should update noise level"
    
    def test_get_noise(self):
        """Should return current noise level."""
        # Arrange
        ground_truth = {"crash_a": 1.0}
        judge = SimulatedJudge(ground_truth, noise=0.3)
        
        # Act
        noise = judge.get_noise()
        
        # Assert
        assert noise == 0.3, "Should return current noise level"
    
    def test_noise_clamping(self):
        """Should clamp noise to [0, 1] range."""
        # Arrange
        ground_truth = {"crash_a": 1.0}
        
        # Act & Assert
        judge_negative = SimulatedJudge(ground_truth, noise=-0.5)
        assert judge_negative.get_noise() == 0.0, "Negative noise should be clamped to 0"
        
        judge_high = SimulatedJudge(ground_truth, noise=1.5)
        assert judge_high.get_noise() == 1.0, "Noise > 1 should be clamped to 1"
    
    def test_empty_crash_list(self):
        """Should handle empty crash list gracefully."""
        # Arrange
        ground_truth = {"crash_a": 1.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        # Act & Assert
        with pytest.raises(ValueError, match="Cannot evaluate empty group"):
            judge.evaluate_group([])
    
    def test_single_crash(self):
        """Should handle single crash correctly."""
        # Arrange
        ground_truth = {"crash_a": 5.0}
        judge = SimulatedJudge(ground_truth, noise=0.1)
        
        crashes = [Crash(crash_id="crash_a", file_path="crash_a.json")]
        
        # Act
        result = judge.evaluate_group(crashes)
        
        # Assert
        assert result.ordered_ids == ["crash_a"], "Should return single crash"
        assert len(result.ordered_ids) == 1, "Should have 1 ordered ID"
