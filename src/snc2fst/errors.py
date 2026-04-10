# src/snc2fst/errors.py


class SncError(Exception):
    """Base exception for all snc2fst errors."""


class AlphabetError(SncError):
    """Raised when an alphabet file cannot be loaded or is invalid."""
