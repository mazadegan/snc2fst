"""Recursive descent parser for the S&C DSL.

Public API:
    parse(expr: str) -> ast.Expr
    collect_errors(...) -> list[str]
    ParseError
"""

import re
from typing import Literal, cast

from snc2fst import dsl_ast as ast
from snc2fst.errors import ParseError, TokenizationError

_OPERATORS = frozenset(
    {
        "in?",
        "if",
        "unify",
        "subtract",
        "proj",
    }
)

_TOKEN_RE = re.compile(
    r"""
    (?:\s+|;[^\n]*)       # whitespace and line comments — skip
    |([()[\]{}&,:])       # punctuation
    |([+\-])              # sign
    |([0-9]+)             # integer
    |([^\W\d_][^\W_]*\??) # name, keyword, or operator (Unicode letters + optional ?)
    |(.)                  # unexpected character — error
    """,  # noqa: E501
    re.VERBOSE,
)

_NAME_RE = re.compile(r"[^\W\d_][^\W_]*")


def parse(expr: str) -> ast.Expr:
    """Parse a DSL expression string into an AST.

    Raises:
        TokenizationError: If an unexpected character is encountered.
        ParseError: If the expression is syntactically invalid.
    """
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    node = parser.parse_expr()
    if parser.peek() is not None:
        raise ParseError(
            f"Unexpected token after expression: {parser.peek()!r}"
        )
    return node


def _tokenize(text: str) -> list[str]:
    """Lex a DSL expression string into a flat list of tokens.

    Whitespace and line comments (';' to end of line) are silently skipped.
    Raises ParseError on any unrecognized character.
    """
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if tok:  # if punctuation, sign, integer, or name/keyword/operator
            tokens.append(tok)
        elif m.group(5):
            raise TokenizationError(m.group(5))
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, value: str) -> str:
        tok = self.peek()
        if tok != value:
            if tok is None:
                raise ParseError(
                    f"Expected {value!r} but reached end of input."
                )
            raise ParseError(f"Expected {value!r}, got {tok!r}")
        return self.consume()

    def parse_expr(self) -> ast.Expr:
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of input")
        if tok == "(":
            return self._parse_paren()
        if tok == "[":
            return self._parse_bracket()
        if tok == "{":
            return self._parse_feature_bundle()
        if tok == "&":
            return self._parse_symbol()
        if tok == "INR":
            self.consume()
            return self._maybe_index(ast.Inr())
        if tok == "TRM":
            self.consume()
            return self._maybe_index(ast.Trm())
        raise ParseError(f"Unexpected token: {tok!r}")

    def _maybe_index(self, seq: ast.Inr | ast.Trm) -> ast.Expr:
        """Parse INR[N], INR[N:M], or bare INR/TRM."""
        if self.peek() != "[":
            return seq
        saved = self.pos
        self.consume()  # consume '['
        tok = self.peek()
        if tok is None or not re.fullmatch(r"[0-9]+", tok):
            self.pos = (
                saved  # restore position — '[' belongs to something else
            )
            return seq
        start = int(self.consume())
        if self.peek() == ":":
            self.consume()
            tok2 = self.peek()
            if tok2 is None or not re.fullmatch(r"[0-9]+", tok2):
                raise ParseError(f"Expected integer after ':', got {tok2!r}")
            end = int(self.consume())
        else:
            end = start
        self.expect("]")
        return ast.Slice(start, end, seq)

    def _parse_paren(self) -> ast.Expr:
        self.expect("(")
        op = self.peek()
        if op in _OPERATORS:
            self.consume()
            args: list[ast.Expr] = []
            if op == "proj":
                # (proj SEGMENT (F G ...))
                if self.peek() is None or self.peek() == ")":
                    raise ParseError("'proj' requires 2 arguments, got 0")
                args.append(self.parse_expr())
                if self.peek() != "(":
                    raise ParseError(
                        "'proj': argument 2 must be a feature name list e.g. (Voice Back)"  # noqa: E501
                    )
                args.append(self._parse_proj_names())
            else:
                while self.peek() != ")":
                    if self.peek() is None:
                        raise ParseError(f"Unclosed '(' for operator '{op}'")
                    args.append(self.parse_expr())
            self.expect(")")
            return self._make_node(op, args)
        # Bare parentheses = implicit concat
        args = []
        while self.peek() != ")":
            if self.peek() is None:
                raise ParseError("Unclosed '(' in implicit concat sequence")
            args.append(self.parse_expr())
        self.expect(")")
        if not args:
            raise ParseError(
                "Empty parentheses — implicit concat requires at least 1 element"  # noqa: E501
            )
        return ast.Concat(args=tuple(args))

    def _make_node(self, op: str, args: list[ast.Expr]) -> ast.Expr:
        def check_argc(n: int):
            if len(args) != n:
                raise ParseError(
                    f"'{op}' requires {n} argument(s), got {len(args)}"
                )

        match op:
            case "in?":
                check_argc(2)
                if not isinstance(args[1], ast.NcSequence):
                    raise ParseError(
                        "'in?': argument 2 must be a natural class sequence e.g. [{+F -G}]"  # noqa: E501
                    )
                return ast.InClass(sequence=args[0], nc_sequence=args[1])
            case "if":
                check_argc(3)
                return ast.If(cond=args[0], then=args[1], else_=args[2])
            case "unify":
                check_argc(2)
                if isinstance(args[1], (ast.FeatureNames, ast.NcSequence)):
                    raise ParseError(
                        "'unify': argument 2 must be a feature bundle e.g. {+F -G}"  # noqa: E501
                        " or a segment expression"
                    )
                return ast.Unify(segment=args[0], features=args[1])
            case "subtract":
                check_argc(2)
                if not isinstance(args[1], ast.FeatureSpec):
                    raise ParseError(
                        "'subtract': argument 2 must be a feature bundle e.g. {+F -G}"  # noqa: E501
                    )
                return ast.Subtract(segment=args[0], features=args[1])
            case "proj":
                check_argc(2)
                if not isinstance(args[1], ast.FeatureNames):
                    raise ParseError(
                        "'proj': argument 2 must be a feature name list e.g. (Voice Back)"  # noqa: E501
                    )
                return ast.Project(segment=args[0], names=args[1])
            case _:
                raise ParseError(f"Unknown operator: {op!r}")

    def _parse_feature_bundle(self) -> ast.FeatureSpec:
        """Parse {+F -G ...} — a feature bundle."""
        self.expect("{")
        features: list[ast.ValuedFeature] = []
        while self.peek() != "}":
            if self.peek() is None:
                raise ParseError("Unclosed '{'")
            tok = self.peek()
            if tok == ",":
                raise ParseError(
                    "Commas are not allowed in feature bundles, use spaces instead. "  # noqa: E501
                    "Write {+F -G}, not {+F, -G}."
                )
            if tok not in ("+", "-"):
                raise ParseError(
                    f"Expected '+' or '-' in feature bundle, got {tok!r}"
                )
            sign = cast(Literal["+", "-"], self.consume())
            name = self.peek()
            if name is None or not _NAME_RE.fullmatch(name):
                raise ParseError(
                    f"Expected feature name after '{sign}', got {name!r}"
                )
            self.consume()
            features.append(ast.ValuedFeature(sign=sign, name=name))
        self.expect("}")
        return ast.FeatureSpec(features=tuple(features))

    def _parse_bracket(self) -> ast.NcSequence:
        """Parse [{+F} {-G} ...] — a natural class sequence."""
        self.expect("[")
        specs: list[ast.FeatureSpec] = []
        while self.peek() != "]":
            if self.peek() is None:
                raise ParseError("Unclosed '['")
            tok = self.peek()
            if tok == ",":
                raise ParseError(
                    "Commas are not allowed in natural class sequences, use spaces instead. "  # noqa: E501
                    "Write [{+F} {-G}], not [{+F}, {-G}]."
                )
            if tok != "{":
                raise ParseError(
                    f"Expected '{{' inside natural class sequence, got {tok!r}. "  # noqa: E501
                    "Use [{+F -G}] for a natural class."
                )
            specs.append(self._parse_feature_bundle())
        self.expect("]")
        return ast.NcSequence(specs=tuple(specs))

    def _parse_proj_names(self) -> ast.FeatureNames:
        """Parse (F G ...) — a list of bare feature names for proj."""
        self.expect("(")
        names: list[str] = []
        while self.peek() != ")":
            tok = self.peek()
            if tok is None:
                raise ParseError("Unclosed '(' in feature name list")
            if not _NAME_RE.fullmatch(tok):
                raise ParseError(
                    f"Expected feature name in proj list, got {tok!r}"
                )
            names.append(self.consume())
        self.expect(")")
        if not names:
            raise ParseError("proj feature name list cannot be empty")
        return ast.FeatureNames(names=tuple(names))

    def _parse_symbol(self) -> ast.Symbol:
        """Parse &name, references a segment literal."""
        self.expect("&")
        name = self.peek()
        if name is None or not _NAME_RE.fullmatch(name):
            raise ParseError(f"Expected segment name after '&', got {name!r}")
        self.consume()
        return ast.Symbol(name=name)


def collect_errors(
    node: ast.Expr,
    rule_id: str,
    inr_len: int,
    trm_len: int,
    valid_segments: set[str],
    valid_features: set[str],
) -> list[str]:
    """Walk a parsed Out AST and return all semantic errors."""
    errors: list[str] = []

    def check_features(features: tuple[ast.ValuedFeature, ...]):
        for vf in features:
            if vf.name not in valid_features:
                errors.append(
                    f"Rule '{rule_id}': undefined feature '{vf.name}' in Out expression."  # noqa: E501
                )

    def walk(n: ast.Expr):
        match n:
            case ast.Slice(start=s, end=e, sequence=seq):
                if s < 1 or e < 1:
                    errors.append(
                        f"Rule '{rule_id}': INR/TRM[{s}:{e}] — indices must be >= 1."  # noqa: E501
                    )
                elif s > e:
                    errors.append(
                        f"Rule '{rule_id}': INR/TRM[{s}:{e}] — start must be <= end."  # noqa: E501
                    )
                elif isinstance(seq, ast.Inr) and e > inr_len:
                    errors.append(
                        f"Rule '{rule_id}': INR[{s}:{e}] out of bounds"
                        f" — INR has length {inr_len}."
                    )
                elif isinstance(seq, ast.Trm) and e > trm_len:
                    errors.append(
                        f"Rule '{rule_id}': TRM[{s}:{e}] out of bounds"
                        f" — TRM has length {trm_len}."
                    )
                walk(seq)
            case ast.Symbol(name=name):
                if name not in valid_segments:
                    errors.append(
                        f"Rule '{rule_id}': undefined segment symbol '{name}'."
                    )
            case ast.Unify(segment=seg, features=fs):
                if isinstance(fs, ast.FeatureSpec):
                    check_features(fs.features)
                else:
                    walk(fs)
                walk(seg)
            case ast.Subtract(segment=seg, features=fs):
                check_features(fs.features)
                walk(seg)
            case ast.Project(segment=seg, names=fn):
                for name in fn.names:
                    if name not in valid_features:
                        errors.append(
                            f"Rule '{rule_id}': undefined feature '{name}' in Out expression."  # noqa: E501
                        )
                walk(seg)
            case ast.InClass(sequence=seq, nc_sequence=nc):
                for spec in nc.specs:
                    check_features(spec.features)
                walk(seq)
            case ast.If(cond=cond, then=then, else_=else_):
                walk(cond)
                walk(then)
                walk(else_)
            case ast.Concat(args=args):
                for arg in args:
                    walk(arg)
            case ast.FeatureSpec(features=features):
                check_features(features)
            case (
                _
            ):  # Inr, Trm, FeatureNames, NcSequence have no errors to check
                pass

    walk(node)
    return errors
