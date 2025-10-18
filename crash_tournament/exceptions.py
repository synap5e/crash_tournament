"""
Exception classes for the crash tournament system.

Centralized location for all custom exceptions to avoid circular imports.
"""


class JudgeError(Exception):
    """Base exception for all judge-related errors."""
    pass


class ValidationError(Exception):
    """Base exception for validation-related errors."""
    pass


class ConfigurationError(Exception):
    """Base exception for configuration-related errors."""
    pass