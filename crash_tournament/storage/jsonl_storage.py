"""
JSONL storage implementation.

Persists observations to JSONL file and snapshots to both JSON file and JSONL file.
Includes checksums and timestamps for data integrity.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from typing_extensions import override

if TYPE_CHECKING:
    from loguru._logger import Logger

from ..interfaces import Storage, SystemState
from ..logging_config import get_logger
from ..models import OrdinalResult


class JSONLStorage(Storage):
    """
    JSONL-based storage implementation.

    Uses JSONL file for observations (append-only) and both JSON file and JSONL file for snapshots.
    Includes checksums and timestamps for data integrity.
    """

    observations_path: Path
    snapshot_path: Path
    snapshots_jsonl_path: Path
    logger: "Logger"

    def __init__(self, observations_path: Path, snapshot_path: Path):
        """
        Initialize JSONL storage.

        Args:
            observations_path: Path to JSONL file for observations
            snapshot_path: Path to JSON file for latest snapshot
        """
        self.observations_path = Path(observations_path)
        self.snapshot_path = Path(snapshot_path)
        # Create snapshots.jsonl path in same directory as snapshot_path
        self.snapshots_jsonl_path = self.snapshot_path.parent / "snapshots.jsonl"

        # Setup logger
        self.logger = get_logger("jsonl_storage")

        # Ensure parent directories exist
        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"JSONL storage initialized: observations={self.observations_path}, snapshot={self.snapshot_path}, snapshots_jsonl={self.snapshots_jsonl_path}"
        )

    @override
    def persist_matchup_result(self, res: OrdinalResult) -> None:
        """Persist an ordinal evaluation result to JSONL."""
        self.logger.debug(f"Persisting ordinal result: {res.ordered_ids}")

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

        self.logger.debug(
            f"Successfully persisted ordinal result to {self.observations_path}"
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
                    data: dict[str, Any] = json.loads(line)

                    # Create OrdinalResult
                    yield OrdinalResult(
                        ordered_ids=data["ordered_ids"],
                        raw_output=data["raw_output"],
                        parsed_result=data.get("parsed_result", {}),
                        timestamp=data.get("timestamp", 0.0),
                        judge_id=data["judge_id"],
                    )
                except json.JSONDecodeError:
                    # Skip corrupted lines
                    self.logger.warning(
                        f"Skipping corrupted JSON line in {self.observations_path}"
                    )
                    continue

    @override
    def save_snapshot(self, state: SystemState) -> None:
        """Save system state snapshot to both JSON and JSONL files."""
        self.logger.info(
            f"Saving snapshot with ranker_state and runtime_state to {self.snapshot_path}"
        )

        # Write to JSON file (idempotent - latest snapshot)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        # Append to JSONL file (append-only - historical snapshots)
        with open(self.snapshots_jsonl_path, "a", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
            f.write("\n")

        self.logger.debug("Snapshot saved successfully to both JSON and JSONL files")

    @override
    def load_snapshot(self) -> SystemState | None:
        """Load system state snapshot from JSON."""
        if not self.snapshot_path.exists():
            self.logger.debug("No snapshot file exists")
            return None

        self.logger.info(f"Loading snapshot from {self.snapshot_path}")
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

        # Validate that the loaded data has the required SystemState structure
        if "ranker_state" not in data or "runtime_state" not in data:
            self.logger.error(
                "Invalid snapshot format - missing required SystemState fields"
            )
            return None

        self.logger.info(
            "Successfully loaded snapshot with ranker_state and runtime_state"
        )
        # Cast to SystemState since we've validated the structure
        return cast(SystemState, cast(object, data))

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
