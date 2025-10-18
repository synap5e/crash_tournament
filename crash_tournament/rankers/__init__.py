"""
Ranker implementations.

Provides implementations of the Ranker interface for maintaining crash rankings
using various ranking algorithms.

Available implementations:
- TrueSkillRanker: Uses Microsoft TrueSkill algorithm for ranking crashes
  with support for k-way comparisons and uncertainty tracking
"""

from .trueskill_ranker import TrueSkillRanker

__all__ = ["TrueSkillRanker"]
