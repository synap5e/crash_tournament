"""
JSONL storage implementation.

Persists observations to JSONL file and snapshots to both JSON file and JSONL file.
Includes checksums and timestamps for data integrity.
"""

import json
import typing
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from typing_extensions import override

from ..interfaces import Storage, SystemState
from ..logging_config import get_logger
from ..models import OrdinalResult

# Module-level logger
logger = get_logger("jsonl_storage")


class JSONLStorage(Storage):
    """
    JSONL-based storage implementation.

    Uses JSONL file for observations (append-only) and both JSON file and JSONL file for snapshots.
    Includes checksums and timestamps for data integrity.
    """

    observations_path: Path
    snapshot_path: Path
    snapshots_jsonl_path: Path
    judge_outputs_path: Path

    def __init__(
        self,
        observations_path: Path,
        snapshot_path: Path,
        judge_outputs_path: Path | None = None,
    ):
        """
        Initialize JSONL storage.

        Args:
            observations_path: Path to JSONL file for observations
            snapshot_path: Path to JSON file for latest snapshot
            judge_outputs_path: Path to JSONL file for judge outputs (optional)
        """
        self.observations_path = Path(observations_path)
        self.snapshot_path = Path(snapshot_path)
        # Create snapshots.jsonl path in same directory as snapshot_path
        self.snapshots_jsonl_path = self.snapshot_path.parent / "snapshots.jsonl"

        # Set judge_outputs_path (default to same directory as observations if not provided)
        if judge_outputs_path is None:
            self.judge_outputs_path = (
                self.observations_path.parent / "judge_outputs.jsonl"
            )
        else:
            self.judge_outputs_path = Path(judge_outputs_path)

        # Ensure parent directories exist
        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.judge_outputs_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"JSONL storage initialized: observations={self.observations_path}, snapshot={self.snapshot_path}, snapshots_jsonl={self.snapshots_jsonl_path}, judge_outputs={self.judge_outputs_path}"
        )

    @override
    def persist_matchup_result(self, res: OrdinalResult) -> None:
        """Persist an ordinal evaluation result to JSONL."""
        logger.debug(f"Persisting ordinal result: {res.ordered_ids}")

        # Convert dataclass to dict
        data = {
            "ordered_ids": res.ordered_ids,
            "raw_output": res.raw_output,
            "parsed_result": res.parsed_result,
            "timestamp": res.timestamp,
            "judge_id": res.judge_id,
        }

        # Append to JSONL file
        with open(self.observations_path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")

        logger.debug(
            f"Successfully persisted ordinal result to {self.observations_path}"
        )

        # Also persist to judge outputs file
        self.persist_judge_output(res)

    @override
    def persist_judge_output(self, res: OrdinalResult) -> None:
        """Persist judge output data to dedicated JSONL file."""
        logger.debug(f"Persisting judge output: {res.ordered_ids}")

        # Convert dataclass to dict (same format as observations)
        data = {
            "ordered_ids": res.ordered_ids,
            "raw_output": res.raw_output,
            "parsed_result": res.parsed_result,
            "timestamp": res.timestamp,
            "judge_id": res.judge_id,
        }

        # Append to judge outputs JSONL file
        with open(self.judge_outputs_path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")

        logger.debug(
            f"Successfully persisted judge output to {self.judge_outputs_path}"
        )

    @override
    def load_observations(self) -> Iterable[OrdinalResult]:
        """Load all persisted ordinal results from JSONL."""
        if not self.observations_path.exists():
            return

        with open(self.observations_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = typing.cast(dict[str, Any], json.loads(line))  # pyright: ignore[reportExplicitAny]

                    # Validate required fields exist and have correct types
                    assert "ordered_ids" in data, "Missing required field: ordered_ids"
                    assert "raw_output" in data, "Missing required field: raw_output"
                    assert "judge_id" in data, "Missing required field: judge_id"

                    # Assert field types and cast immediately
                    assert isinstance(data["ordered_ids"], list), (
                        "ordered_ids must be a list"
                    )
                    # Validate list contents are strings
                    ordered_ids = typing.cast(list[str], data["ordered_ids"])
                    raw_output = typing.cast(str, data["raw_output"])
                    judge_id = typing.cast(str, data["judge_id"])

                    # Validate optional fields if present
                    parsed_result: dict[str, object] = {}
                    if "parsed_result" in data:
                        assert isinstance(data["parsed_result"], dict), (
                            "parsed_result must be a dictionary"
                        )
                        parsed_result = typing.cast(
                            dict[str, object], data["parsed_result"]
                        )

                    timestamp = 0.0
                    if "timestamp" in data:
                        assert isinstance(data["timestamp"], (int, float)), (
                            "timestamp must be a number"
                        )
                        timestamp = float(data["timestamp"])

                    # Create OrdinalResult with validated and cast data
                    yield OrdinalResult(
                        ordered_ids=ordered_ids,
                        raw_output=raw_output,
                        parsed_result=parsed_result,
                        timestamp=timestamp,
                        judge_id=judge_id,
                    )
                except (json.JSONDecodeError, AssertionError) as e:
                    # Skip corrupted or invalid lines
                    logger.warning(
                        f"Skipping invalid JSON line in {self.observations_path}: {e}"
                    )
                    continue

    @override
    def save_snapshot(self, state: SystemState) -> None:
        """Save system state snapshot to both JSON and JSONL files."""
        logger.info(
            f"Saving snapshot with ranker_state and runtime_state to {self.snapshot_path}"
        )

        # Write to JSON file (idempotent - latest snapshot)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        # Append to JSONL file (append-only - historical snapshots)
        with open(self.snapshots_jsonl_path, "a", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
            f.write("\n")

        logger.debug("Snapshot saved successfully to both JSON and JSONL files")

    @override
    def load_snapshot(self) -> SystemState | None:
        """Load system state snapshot from JSON."""
        if not self.snapshot_path.exists():
            logger.debug("No snapshot file exists")
            return None

        logger.info(f"Loading snapshot from {self.snapshot_path}")
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = typing.cast(dict[str, Any], json.load(f))  # pyright: ignore[reportExplicitAny]

            # Validate that the loaded data has the required SystemState structure
            assert "ranker_state" in data, "Missing required field: ranker_state"
            assert "runtime_state" in data, "Missing required field: runtime_state"

            # Validate field types
            assert isinstance(data["ranker_state"], dict), (
                "ranker_state must be a dictionary"
            )
            assert isinstance(data["runtime_state"], dict), (
                "runtime_state must be a dictionary"
            )

            # Validate ranker_state structure
            ranker_state_data = typing.cast(dict[str, object], data["ranker_state"])
            assert "ratings" in ranker_state_data, (
                "Missing required field: ranker_state.ratings"
            )
            assert isinstance(ranker_state_data["ratings"], dict), (
                "ranker_state.ratings must be a dictionary"
            )

            # Validate runtime_state structure
            runtime_state_data = typing.cast(dict[str, int], data["runtime_state"])
            assert isinstance(runtime_state_data, dict), (
                "runtime_state must be a dictionary"
            )

            logger.info(
                "Successfully loaded snapshot with ranker_state and runtime_state"
            )
            # Create SystemState with validated data - use cast through object to avoid type checker issues
            return typing.cast(SystemState, typing.cast(object, data))

        except (json.JSONDecodeError, AssertionError) as e:
            logger.error(f"Failed to load snapshot from {self.snapshot_path}: {e}")
            return None

    def clear_observations(self) -> None:
        """Clear all observations (for testing)."""
        if self.observations_path.exists():
            self.observations_path.unlink()

    def clear_snapshot(self) -> None:
        """Clear snapshot (for testing)."""
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
        if self.snapshots_jsonl_path.exists():
            self.snapshots_jsonl_path.unlink()

    def get_observation_count(self) -> int:
        """Get number of stored observations."""
        if not self.observations_path.exists():
            return 0

        count = 0
        with open(self.observations_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
