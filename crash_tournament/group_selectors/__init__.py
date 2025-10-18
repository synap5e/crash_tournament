"""
Selector implementations.

Provides implementations of the Selector interface for choosing which crash
matchups to evaluate next.

Available implementations:
- RandomSelector: Randomly selects crash matchups for evaluation
- UncertaintySelector: (Planned) Selects matchups based on uncertainty sampling
"""

from .random_selector import RandomSelector

__all__ = ["RandomSelector"]
