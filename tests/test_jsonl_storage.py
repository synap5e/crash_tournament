"""
Tests for JSONLStorage implementation.

Focus on persistence and data integrity.
"""

import json
import tempfile
from pathlib import Path

from crash_tournament.interfaces import SystemState
from crash_tournament.models import OrdinalResult
from crash_tournament.storage.jsonl_storage import JSONLStorage


class TestJSONLStorage:
    """Test JSONLStorage behavior through public interface."""

    def test_persist_and_load_single_observation(self) -> None:
        """Write and read one result should work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            result = OrdinalResult(
                ordered_ids=["a", "b", "c"],
                raw_output="test output",
                parsed_result={"rationale_top": "a is most exploitable"},
            )

            # Act
            storage.persist_matchup_result(result)
            loaded_results = list(storage.load_observations())

            # Assert
            assert len(loaded_results) == 1, "Should load one result"
            loaded = loaded_results[0]
            assert loaded.ordered_ids == ["a", "b", "c"]
            assert loaded.raw_output == "test output"
            assert loaded.parsed_result["rationale_top"] == "a is most exploitable"
            assert len(loaded.ordered_ids) == 3

    def test_persist_multiple_observations(self) -> None:
        """Append-only semantics should work for multiple observations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            results = [
                OrdinalResult(
                    ordered_ids=["a", "b"],
                    raw_output="test1",
                    parsed_result={"rationale_top": "a beats b"},
                ),
                OrdinalResult(
                    ordered_ids=["c", "d", "e"],
                    raw_output="test2",
                    parsed_result={"rationale_top": "c > d > e"},
                ),
            ]

            # Act
            for result in results:
                storage.persist_matchup_result(result)

            loaded_results = list(storage.load_observations())

            # Assert
            assert len(loaded_results) == 2, "Should load two results"
            assert loaded_results[0].ordered_ids == ["a", "b"]
            assert loaded_results[1].ordered_ids == ["c", "d", "e"]

    def test_snapshot_save_and_load(self) -> None:
        """Idempotent snapshot writes should work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            test_state: SystemState = {
                "ranker_state": {
                    "ratings": {
                        "crash_a": {"mu": 30.0, "sigma": 5.0},
                        "crash_b": {"mu": 20.0, "sigma": 6.0},
                    },
                    "statistics": {
                        "eval_counts": {"crash_a": 1, "crash_b": 1},
                        "win_counts": {"crash_a": 1, "crash_b": 0},
                        "rankings": {"crash_a": [1], "crash_b": [2]},
                        "group_sizes": {"crash_a": [2], "crash_b": [2]},
                    },
                },
                "runtime_state": {
                    "evaluated_matchups": 1,
                    "total_evaluations": 1,
                    "failed_evaluations": 0,
                    "last_milestone": 0,
                },
            }

            # Act
            storage.save_snapshot(test_state)
            loaded_state = storage.load_snapshot()

            # Assert
            assert loaded_state is not None, "Should load snapshot"
            assert loaded_state == test_state, "Snapshot should match original"

            # Test idempotent write
            storage.save_snapshot(test_state)
            loaded_state2 = storage.load_snapshot()
            assert loaded_state2 == test_state, "Second write should not change content"

    def test_checksum_validation_detects_corruption(self) -> None:
        """Manual file corruption should be detected by checksum validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            result = OrdinalResult(
                ordered_ids=["a", "b"],
                raw_output="test",
                parsed_result={"rationale_top": "a wins"},
            )
            storage.persist_matchup_result(result)

            # Act - manually corrupt the file
            with open(observations_path, "a") as f:
                f.write("corrupted line\n")

            # Assert - should skip corrupted line
            loaded_results = list(storage.load_observations())
            assert len(loaded_results) == 1, "Should load only valid result"
            assert loaded_results[0].ordered_ids == ["a", "b"]

    def test_missing_files_return_empty(self) -> None:
        """Graceful handling of missing files should return empty results."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "nonexistent_observations.jsonl"
            snapshot_path = Path(temp_dir) / "nonexistent_latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            # Act
            observations = list(storage.load_observations())
            snapshot = storage.load_snapshot()

            # Assert
            assert (
                len(observations) == 0
            ), "Should return empty list for missing observations"
            assert snapshot is None, "Should return None for missing snapshot"

    def test_observation_count(self) -> None:
        """Count helper should work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            # Act & Assert
            assert (
                storage.get_observation_count() == 0
            ), "Empty storage should have 0 observations"

            # Add some observations
            for i in range(3):
                result = OrdinalResult(
                    ordered_ids=[f"a{i}", f"b{i}"],
                    raw_output=f"test{i}",
                    parsed_result={"rationale_top": f"a{i} wins"},
                )
                storage.persist_matchup_result(result)

            assert storage.get_observation_count() == 3, "Should count 3 observations"

    def test_clear_observations(self) -> None:
        """Clear observations should remove all data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            # Add some data
            result = OrdinalResult(
                ordered_ids=["a", "b"],
                raw_output="test",
                parsed_result={"rationale_top": "a wins"},
            )
            storage.persist_matchup_result(result)
            assert storage.get_observation_count() == 1

            # Act
            storage.clear_observations()

            # Assert
            assert (
                storage.get_observation_count() == 0
            ), "Should have 0 observations after clear"
            assert not observations_path.exists(), "Observations file should be deleted"

    def test_clear_snapshot(self) -> None:
        """Clear snapshot should remove snapshot data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            # Add snapshot
            test_state: SystemState = {
                "ranker_state": {
                    "ratings": {"test": {"mu": 25.0, "sigma": 8.0}},
                    "statistics": {
                        "eval_counts": {"test": 1},
                        "win_counts": {"test": 1},
                        "rankings": {"test": [1]},
                        "group_sizes": {"test": [2]},
                    },
                },
                "runtime_state": {
                    "evaluated_matchups": 1,
                    "total_evaluations": 1,
                    "failed_evaluations": 0,
                    "last_milestone": 0,
                },
            }
            storage.save_snapshot(test_state)
            assert snapshot_path.exists()

            # Act
            storage.clear_snapshot()

            # Assert
            assert not snapshot_path.exists(), "Snapshot file should be deleted"
            assert (
                storage.load_snapshot() is None
            ), "Should return None for cleared snapshot"

    def test_metadata_included_in_persisted_data(self) -> None:
        """Persisted data should include timestamp and checksum metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            result = OrdinalResult(
                ordered_ids=["a", "b"],
                raw_output="test",
                parsed_result={"rationale_top": "a wins"},
            )

            # Act
            storage.persist_matchup_result(result)

            # Assert - check raw file content
            with open(observations_path, "r") as f:
                line = f.readline().strip()
                data = json.loads(line)

                assert "timestamp" in data, "Should include timestamp"
                assert "ordered_ids" in data, "Should include original data"
                assert data["ordered_ids"] == ["a", "b"]

    def test_snapshot_metadata_included(self) -> None:
        """Snapshot should include timestamp and checksum metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            observations_path = Path(temp_dir) / "observations.jsonl"
            snapshot_path = Path(temp_dir) / "latest_snapshot.json"
            storage = JSONLStorage(observations_path, snapshot_path)

            test_state: SystemState = {
                "ranker_state": {
                    "ratings": {"test": {"mu": 25.0, "sigma": 8.0}},
                    "statistics": {
                        "eval_counts": {"test": 1},
                        "win_counts": {"test": 1},
                        "rankings": {"test": [1]},
                        "group_sizes": {"test": [2]},
                    },
                },
                "runtime_state": {
                    "evaluated_matchups": 1,
                    "total_evaluations": 1,
                    "failed_evaluations": 0,
                    "last_milestone": 0,
                },
            }

            # Act
            storage.save_snapshot(test_state)

            # Assert - check raw file content
            with open(snapshot_path, "r") as f:
                data = json.load(f)

                assert "ranker_state" in data, "Should include ranker_state"
                assert "runtime_state" in data, "Should include runtime_state"
                assert data["ranker_state"]["ratings"]["test"] == {
                    "mu": 25.0,
                    "sigma": 8.0,
                }
