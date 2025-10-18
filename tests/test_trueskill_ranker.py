"""
Tests for TrueSkillRanker implementation.

Focus on k-way to pairwise conversion and ranking updates.
"""

from crash_tournament.models import OrdinalResult
from crash_tournament.rankers.trueskill_ranker import TrueSkillRanker


class TestTrueSkillRanker:
    """Test TrueSkillRanker behavior through public interface."""

    def test_pairwise_update_increases_winner_decreases_loser(self) -> None:
        """Basic 2-way comparison should increase winner score and decrease loser score."""
        # Arrange
        ranker = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["winner", "loser"],
            raw_output="test",
            parsed_result={"rationale_top": "winner beats loser"},
        )

        # Get initial scores
        initial_winner = ranker.get_score("winner")
        initial_loser = ranker.get_score("loser")

        # Act
        ranker.update_with_ordinal(result)

        # Assert
        final_winner = ranker.get_score("winner")
        final_loser = ranker.get_score("loser")

        assert final_winner > initial_winner, "Winner score should increase"
        assert final_loser < initial_loser, "Loser score should decrease"
        assert final_winner > final_loser, "Winner should have higher score than loser"

    def test_kway_conversion_ordering(self) -> None:
        """Verify 4-way [a,b,c,d] correctly updates all ratings in sequence."""
        # Arrange
        ranker = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["a", "b", "c", "d"],
            raw_output="test",
            parsed_result={"rationale_top": "a > b > c > d"},
        )

        # Get initial scores
        initial_scores = {
            crash_id: ranker.get_score(crash_id) for crash_id in ["a", "b", "c", "d"]
        }

        # Act
        ranker.update_with_ordinal(result)

        # Assert
        final_scores = {
            crash_id: ranker.get_score(crash_id) for crash_id in ["a", "b", "c", "d"]
        }

        # All scores should have changed
        for crash_id in ["a", "b", "c", "d"]:
            assert final_scores[crash_id] != initial_scores[crash_id], (
                f"{crash_id} score should change"
            )

        # Final ordering should match input ordering
        assert final_scores["a"] > final_scores["b"], "a should rank higher than b"
        assert final_scores["b"] > final_scores["c"], "b should rank higher than c"
        assert final_scores["c"] > final_scores["d"], "c should rank higher than d"

    def test_weight_scaling_reduces_update_magnitude(self) -> None:
        """Lower weight should result in smaller rating changes."""
        # Arrange
        ranker1 = TrueSkillRanker()
        ranker2 = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["a", "b"],
            raw_output="test",
            parsed_result={"rationale_top": "a beats b"},
        )

        # Act - update with different weights
        ranker1.update_with_ordinal(result, weight=1.0)  # Normal weight
        ranker2.update_with_ordinal(
            result, weight=0.5
        )  # Lower weight (smaller changes)

        # Assert - lower weight should produce smaller changes
        change1_a = abs(ranker1.get_score("a") - 25.0)  # Default mu
        change2_a = abs(ranker2.get_score("a") - 25.0)

        assert change2_a < change1_a, "Lower weight should produce smaller changes"

    def test_unseen_crash_gets_default_rating(self) -> None:
        """New crashes should initialize with default rating."""
        # Arrange
        ranker = TrueSkillRanker()
        new_crash_id = "new_crash"

        # Act
        score = ranker.get_score(new_crash_id)
        uncertainty = ranker.get_uncertainty(new_crash_id)

        # Assert
        assert score == 25.0, "New crash should get default mu"
        assert uncertainty == 8.333333333333334, "New crash should get default sigma"

    def test_snapshot_and_restore(self) -> None:
        """Round-trip serialization should preserve state."""
        # Arrange
        ranker1 = TrueSkillRanker()
        ranker2 = TrueSkillRanker()

        # Update ranker1 with some data
        result = OrdinalResult(
            ordered_ids=["a", "b", "c"],
            raw_output="test",
            parsed_result={"rationale_top": "a > b > c"},
        )
        ranker1.update_with_ordinal(result)

        # Act
        snapshot = ranker1.snapshot()
        ranker2.load_snapshot(snapshot)

        # Assert
        for crash_id in ["a", "b", "c"]:
            assert ranker1.get_score(crash_id) == ranker2.get_score(crash_id), (
                f"Scores should match for {crash_id}"
            )
            assert ranker1.get_uncertainty(crash_id) == ranker2.get_uncertainty(
                crash_id
            ), f"Uncertainties should match for {crash_id}"

    def test_get_score_returns_mu(self) -> None:
        """get_score should return the mu value."""
        # Arrange
        ranker = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["a", "b"],
            raw_output="test",
            parsed_result={"rationale_top": "a beats b"},
        )
        ranker.update_with_ordinal(result)

        # Act
        score_a = ranker.get_score("a")
        score_b = ranker.get_score("b")

        # Assert
        assert isinstance(score_a, float), "Score should be float"
        assert isinstance(score_b, float), "Score should be float"
        assert score_a > score_b, "Winner should have higher score"

    def test_get_uncertainty_returns_sigma(self) -> None:
        """get_uncertainty should return the sigma value."""
        # Arrange
        ranker = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["a", "b"],
            raw_output="test",
            parsed_result={"rationale_top": "a beats b"},
        )
        ranker.update_with_ordinal(result)

        # Act
        uncertainty_a = ranker.get_uncertainty("a")
        uncertainty_b = ranker.get_uncertainty("b")

        # Assert
        assert isinstance(uncertainty_a, float), "Uncertainty should be float"
        assert isinstance(uncertainty_b, float), "Uncertainty should be float"
        assert uncertainty_a > 0, "Uncertainty should be positive"
        assert uncertainty_b > 0, "Uncertainty should be positive"

    def test_multiple_updates_converge(self) -> None:
        """Multiple updates should converge to stable rankings."""
        # Arrange
        ranker = TrueSkillRanker()

        # Act - multiple updates with same ordering
        for _ in range(10):
            result = OrdinalResult(
                ordered_ids=["a", "b", "c"],
                raw_output="test",
                parsed_result={"rationale_top": "consistent ordering"},
            )
            ranker.update_with_ordinal(result)

        # Assert - ordering should be stable
        scores = {
            "a": ranker.get_score("a"),
            "b": ranker.get_score("b"),
            "c": ranker.get_score("c"),
        }

        assert scores["a"] > scores["b"], "a should rank highest"
        assert scores["b"] > scores["c"], "b should rank middle"
        assert scores["a"] > scores["c"], "a should rank higher than c"

    def test_snapshot_contains_all_crashes(self) -> None:
        """Snapshot should contain all crashes that have been seen."""
        # Arrange
        ranker = TrueSkillRanker()
        result = OrdinalResult(
            ordered_ids=["x", "y", "z"],
            raw_output="test",
            parsed_result={"rationale_top": "x > y > z"},
        )
        ranker.update_with_ordinal(result)

        # Act
        snapshot = ranker.snapshot()

        # Assert
        assert "x" in snapshot["ratings"], "Snapshot should contain x"
        assert "y" in snapshot["ratings"], "Snapshot should contain y"
        assert "z" in snapshot["ratings"], "Snapshot should contain z"

        for crash_id in ["x", "y", "z"]:
            assert "mu" in snapshot["ratings"][crash_id], (
                f"Snapshot should contain mu for {crash_id}"
            )
            assert "sigma" in snapshot["ratings"][crash_id], (
                f"Snapshot should contain sigma for {crash_id}"
            )
