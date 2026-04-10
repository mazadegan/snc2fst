# src/snc2fst/errors.py


class SncError(Exception):
    """Base exception for all snc2fst errors."""


class AlphabetError(SncError):
    """Raised when an alphabet file cannot be loaded or is invalid."""


class RuleError(SncError):
    """
    Raised when a rule references invalid features or is otherwise malformed.
    """
