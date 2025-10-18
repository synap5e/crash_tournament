"""
Type stubs for trueskill library.

This module provides type annotations for the trueskill library,
which implements the TrueSkill rating system for multiplayer games.
"""

from typing import Any, Optional, Union

from typing_extensions import Literal

class Rating:
    """A TrueSkill rating representing a player's skill level.

    A rating consists of a mean (mu) and standard deviation (sigma)
    that represent the player's skill level and uncertainty.
    """

    def __init__(self, mu: float = ..., sigma: float = ...) -> None:
        """Initialize a rating with mean and standard deviation.

        Args:
            mu: The mean skill level (default: 25.0)
            sigma: The standard deviation/uncertainty (default: 8.333...)
        """
        ...

    @property
    def mu(self) -> float:
        """The mean skill level."""
        ...

    @property
    def sigma(self) -> float:
        """The standard deviation/uncertainty."""
        ...

    @property
    def pi(self) -> float:
        """The precision (1/sigma^2)."""
        ...

    @property
    def tau(self) -> float:
        """The dynamic factor."""
        ...

    @property
    def exposure(self) -> float:
        """The exposure (mu - 3*sigma)."""
        ...

    def __repr__(self) -> str:
        """String representation of the rating."""
        ...

    def __str__(self) -> str:
        """String representation of the rating."""
        ...

    def __eq__(self, other: object) -> bool:
        """Check equality with another rating."""
        ...

    def __ne__(self, other: object) -> bool:
        """Check inequality with another rating."""
        ...

    def __lt__(self, other: Rating) -> bool:
        """Check if this rating is less than another."""
        ...

    def __le__(self, other: Rating) -> bool:
        """Check if this rating is less than or equal to another."""
        ...

    def __gt__(self, other: Rating) -> bool:
        """Check if this rating is greater than another."""
        ...

    def __ge__(self, other: Rating) -> bool:
        """Check if this rating is greater than or equal to another."""
        ...

    def __add__(self, other: Union[Rating, float]) -> Rating:
        """Add another rating or float to this rating."""
        ...

    def __sub__(self, other: Union[Rating, float]) -> Rating:
        """Subtract another rating or float from this rating."""
        ...

    def __mul__(self, other: float) -> Rating:
        """Multiply this rating by a scalar."""
        ...

    def __truediv__(self, other: float) -> Rating:
        """Divide this rating by a scalar."""
        ...

    def __float__(self) -> float:
        """Convert to float (returns mu)."""
        ...

    def __int__(self) -> int:
        """Convert to int (returns int(mu))."""
        ...

class TrueSkill:
    """TrueSkill environment configuration."""

    def __init__(
        self,
        mu: float = ...,
        sigma: float = ...,
        beta: float = ...,
        tau: float = ...,
        draw_probability: float = ...,
        backend: Optional[Any] = ...,
        env: Optional[Any] = ...,
    ) -> None:
        """Initialize TrueSkill environment.

        Args:
            mu: Initial mean rating
            sigma: Initial standard deviation
            beta: Skill factor
            tau: Dynamic factor
            draw_probability: Probability of a draw
            backend: Backend implementation
            env: Environment reference
        """
        ...

    @property
    def mu(self) -> float:
        """The mean rating."""
        ...

    @property
    def sigma(self) -> float:
        """The standard deviation."""
        ...

    @property
    def beta(self) -> float:
        """The skill factor."""
        ...

    @property
    def tau(self) -> float:
        """The dynamic factor."""
        ...

    @property
    def draw_probability(self) -> float:
        """The draw probability."""
        ...

    def __repr__(self) -> str:
        """String representation of the environment."""
        ...

def rate_1vs1(
    rating1: Rating,
    rating2: Rating,
    drawn: bool = ...,
    min_delta: float = ...,
    env: Optional[TrueSkill] = ...,
) -> tuple[Rating, Rating]:
    """Rate a 1v1 match between two players.

    Args:
        rating1: Rating of the first player
        rating2: Rating of the second player
        drawn: Whether the match was a draw
        min_delta: Minimum delta for convergence
        env: TrueSkill environment (uses global if None)

    Returns:
        Tuple of (new_rating1, new_rating2)
    """
    ...

def rate(
    rating_groups: Any,
    ranks: Optional[Any] = ...,
    min_delta: float = ...,
    env: Optional[TrueSkill] = ...,
) -> Any:
    """Rate a multi-player match.

    Args:
        rating_groups: Groups of ratings to rate
        ranks: Optional ranks for the groups
        min_delta: Minimum delta for convergence
        env: TrueSkill environment (uses global if None)

    Returns:
        Updated ratings
    """
    ...

def setup(
    mu: float = ...,
    sigma: float = ...,
    beta: float = ...,
    tau: float = ...,
    draw_probability: float = ...,
    backend: Optional[Any] = ...,
    env: Optional[Any] = ...,
) -> TrueSkill:
    """Set up the global TrueSkill environment.

    Args:
        mu: Initial mean rating (default: 25.0)
        sigma: Initial standard deviation (default: 8.333...)
        beta: Skill factor (default: 4.166...)
        tau: Dynamic factor (default: 0.083...)
        draw_probability: Probability of a draw (default: 0.1)
        backend: Backend implementation
        env: Environment reference

    Returns:
        The configured TrueSkill environment
    """
    ...

def quality_1vs1(
    rating1: Rating, rating2: Rating, env: Optional[TrueSkill] = ...
) -> float:
    """Calculate the quality of a 1v1 match.

    Args:
        rating1: Rating of the first player
        rating2: Rating of the second player
        env: TrueSkill environment (uses global if None)

    Returns:
        Quality score between 0 and 1
    """
    ...

def quality(rating_groups: Any, env: Optional[TrueSkill] = ...) -> float:
    """Calculate the quality of a multi-player match.

    Args:
        rating_groups: Groups of ratings
        env: TrueSkill environment (uses global if None)

    Returns:
        Quality score between 0 and 1
    """
    ...

def win_probability(
    rating1: Rating, rating2: Rating, env: Optional[TrueSkill] = ...
) -> float:
    """Calculate the probability that rating1 beats rating2.

    Args:
        rating1: Rating of the first player
        rating2: Rating of the second player
        env: TrueSkill environment (uses global if None)

    Returns:
        Win probability between 0 and 1
    """
    ...

def draw_probability(
    rating1: Rating, rating2: Rating, env: Optional[TrueSkill] = ...
) -> float:
    """Calculate the probability of a draw between two ratings.

    Args:
        rating1: Rating of the first player
        rating2: Rating of the second player
        env: TrueSkill environment (uses global if None)

    Returns:
        Draw probability between 0 and 1
    """
    ...

def global_env() -> TrueSkill:
    """Get the global TrueSkill environment.

    Returns:
        The current global environment
    """
    ...

def set_global_env(env: TrueSkill) -> None:
    """Set the global TrueSkill environment.

    Args:
        env: The environment to set as global
    """
    ...
