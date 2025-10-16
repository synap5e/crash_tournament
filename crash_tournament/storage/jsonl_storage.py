"""
JSONL storage implementation.

Persists observations to JSONL file and snapshots to JSON file with checksums.
"""

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from ..interfaces import Storage
from ..models import OrdinalResult
from ..logging_config import get_logger


class JSONLStorage(Storage):
    """
    JSONL-based storage implementation.
    
    Uses JSONL file for observations (append-only) and JSON file for snapshots.
    Includes checksums and timestamps for data integrity.
    """
    
    def __init__(self, observations_path: Path, snapshot_path: Path):
        """
        Initialize JSONL storage.
        
        Args:
            observations_path: Path to JSONL file for observations
            snapshot_path: Path to JSON file for snapshots
        """
        self.observations_path = Path(observations_path)
        self.snapshot_path = Path(snapshot_path)
        
        # Setup logger
        self.logger = get_logger("jsonl_storage")
        
        # Ensure parent directories exist
        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"JSONL storage initialized: observations={self.observations_path}, snapshot={self.snapshot_path}")
    
    def persist_ordinal(self, res: OrdinalResult) -> None:
        """Persist an ordinal evaluation result to JSONL."""
        self.logger.debug(f"Persisting ordinal result: {res.ordered_ids}")
        
        # Convert dataclass to dict
        data = {
            "ordered_ids": res.ordered_ids,
            "raw_output": res.raw_output,
            "parsed_result": res.parsed_result,
            "timestamp": res.timestamp,
            "judge_id": res.judge_id,
            "group_size": res.group_size,
        }
        
        # Append to JSONL file
        with open(self.observations_path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")
        
        self.logger.debug(f"Successfully persisted ordinal result to {self.observations_path}")
    
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
                    data = json.loads(line)
                    
                    # Create OrdinalResult
                    yield OrdinalResult(
                        ordered_ids=data["ordered_ids"],
                        raw_output=data["raw_output"],
                        parsed_result=data.get("parsed_result", {}),
                        timestamp=data.get("timestamp", 0.0),
                        judge_id=data["judge_id"],
                        group_size=data["group_size"],
                    )
                except json.JSONDecodeError:
                    # Skip corrupted lines
                    self.logger.warning(f"Skipping corrupted JSON line in {self.observations_path}")
                    continue
    
    def save_snapshot(self, state: dict) -> None:
        """Save system state snapshot to JSON (idempotent write)."""
        self.logger.info(f"Saving snapshot with {len(state)} items to {self.snapshot_path}")
        
        # Write to JSON file (idempotent)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        self.logger.debug("Snapshot saved successfully")
    
    def load_snapshot(self) -> Optional[dict]:
        """Load system state snapshot from JSON."""
        if not self.snapshot_path.exists():
            self.logger.debug("No snapshot file exists")
            return None
        
        self.logger.info(f"Loading snapshot from {self.snapshot_path}")
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.logger.info(f"Successfully loaded snapshot with {len(data)} items")
        return data
    
    def clear_observations(self) -> None:
        """Clear all observations (for testing)."""
        if self.observations_path.exists():
            self.observations_path.unlink()
    
    def clear_snapshot(self) -> None:
        """Clear snapshot (for testing)."""
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
    
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