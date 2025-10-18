"""
Random selector implementation.

Simple stateless selector for testing/baseline.
"""

import random
from collections.abc import Sequence
from typing_extensions import override

from ..interfaces import Ranker, Selector


class RandomSelector(Selector):
    """Random matchup selector - for testing/baseline."""
    
    def __init__(self, ranker: Ranker):
        """Initialize random selector.
        
        Args:
            ranker: Ranker instance (not used by RandomSelector but kept for interface 
                   consistency with future selectors like UncertaintySelector that will 
                   need access to ranking data for intelligent selection)
        """
        self.ranker = ranker
        from ..logging_config import get_logger
        self.logger = get_logger("random_selector")
    
    @override
    def select_matchup(self, all_crash_ids: Sequence[str], matchup_size: int) -> Sequence[str] | None:
        """Return random matchup of crashes."""
        if len(all_crash_ids) < 2:
            self.logger.warning("Insufficient crashes for matchup")
            return None
        
        size = min(matchup_size, len(all_crash_ids))
        matchup = random.sample(list(all_crash_ids), size)
        self.logger.debug(f"Selected random matchup of size {size}: {matchup}")
        return matchup
