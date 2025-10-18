"""
Least-runs selector implementation.

Selects crashes randomly but prioritizes those with the fewest evaluations.
Ensures even coverage across all crashes before any crash gets evaluated
many more times than others.
"""

import random
from collections.abc import Sequence

from typing_extensions import override

from ..interfaces import Ranker, Selector
from ..logging_config import get_logger

# Module-level logger
logger = get_logger("least_runs_selector")


class LeastRunsSelector(Selector):
    """Selector that prioritizes crashes with fewer evaluations."""

    def __init__(self, ranker: Ranker):
        """Initialize least-runs selector.

        Args:
            ranker: Ranker instance to query evaluation counts
        """
        self.ranker = ranker

    @override
    def select_matchup(
        self, all_crash_ids: Sequence[str], matchup_size: int
    ) -> Sequence[str] | None:
        """Return matchup prioritizing crashes with fewer evaluations."""
        if len(all_crash_ids) < 2:
            logger.warning("Insufficient crashes for matchup")
            return None

        # Build eval count buckets
        buckets: dict[int, list[str]] = {}
        for crash_id in all_crash_ids:
            eval_count = self.ranker.get_total_eval_count(crash_id)
            if eval_count not in buckets:
                buckets[eval_count] = []
            buckets[eval_count].append(crash_id)

        # Sort buckets by eval count (ascending)
        sorted_counts = sorted(buckets.keys())

        # Fill matchup greedily from lowest buckets
        matchup: list[str] = []
        for count in sorted_counts:
            available = buckets[count]
            random.shuffle(available)  # Randomize within bucket

            needed = matchup_size - len(matchup)
            matchup.extend(available[:needed])

            if len(matchup) >= matchup_size:
                break

        # Trim to exact size if we overshot
        matchup = matchup[:matchup_size]

        logger.debug(f"Selected least-runs matchup of size {len(matchup)}: {matchup}")
        return matchup
