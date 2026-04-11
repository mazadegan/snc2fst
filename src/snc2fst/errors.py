# src/snc2fst/errors.py


class SncError(Exception):
    """Base exception for all snc2fst errors."""


class AlphabetError(SncError):
    """Raised when an alphabet file cannot be loaded or is invalid."""


class RuleError(SncError):
    """
    Raised when a rule references invalid features or is otherwise malformed.
    """


class DSLError(SncError):
    """Base class for DSL parsing and validation errors."""


class TokenizationError(DSLError):
    """Raised when an unexpected character is encountered during tokenization.

    Attributes:
        char: The unexpected character that caused the error.
    """

    def __init__(self, char: str):
        self.char = char
        super().__init__(f"Unexpected character: {char!r}")


class ParseError(DSLError):
    """Raised when a syntactically invalid expression is encountered."""


class EvalError(Exception):
    """Raised when a DSL expression cannot be evaluated.

    This may occur when an operator receives a word of the wrong length
    (e.g. a multi-segment word passed to unify), or when a referenced
    segment symbol is not in the inventory.
    """
