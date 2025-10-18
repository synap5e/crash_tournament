"""
Dummy judge implementation for testing.

Provides deterministic and random ranking for testing purposes.
"""

import random
from collections.abc import Sequence

from typing_extensions import override

from ..exceptions import ValidationError
from ..interfaces import Judge
from ..models import Crash, OrdinalResult


class DummyJudge(Judge):
    """
    Dummy judge for testing purposes.

    Provides deterministic or random ranking based on crash IDs.
    """

    def __init__(self, mode: str = "deterministic", seed: int = 42):
        """
        Initialize dummy judge.

        Args:
            mode: "deterministic" or "random"
            seed: Random seed for reproducible results
        """
        self.mode = mode
        self.seed = seed
        self.judge_id = f"dummy_{mode}"

        if mode == "random":
            random.seed(seed)

    @override
    def evaluate_matchup(self, crashes: Sequence[Crash]) -> OrdinalResult:
        """
        Evaluate group of crashes using dummy logic.

        Args:
            crashes: Sequence of crashes to evaluate
            grading: Ignored for dummy judge

        Returns:
            OrdinalResult with ordered crash IDs
        """
        if not crashes:
            raise ValidationError("Cannot evaluate empty group")

        crash_ids = [crash.crash_id for crash in crashes]

        if self.mode == "deterministic":
            # Sort by crash_id for deterministic ordering
            ordered_ids = sorted(crash_ids)
        elif self.mode == "random":
            # Random shuffle
            ordered_ids = crash_ids.copy()
            random.shuffle(ordered_ids)
        else:
            raise ValidationError(f"Unknown mode: {self.mode}")

        # Generate simple rationale
        rationale = f"Dummy {self.mode} ranking of {len(crashes)} crashes"

        return OrdinalResult(
            ordered_ids=ordered_ids,
            raw_output=f"Dummy judge output for {len(crashes)} crashes",
            parsed_result={"rationale": rationale},
            judge_id=self.judge_id,
        )

    def test_connection(self) -> bool:
        """Test connection (always succeeds for dummy judge)."""
        return True
