"""Recursive descent parser for the S&C DSL.

Public API:
    parse(expr: str) -> ast.Expr
    collect_errors(...) -> list[str]
    ParseError
"""

import re
from snc2fst import ast

_OPERATORS = frozenset({
    "nth", "in?", "models?", "if",
    "unify", "subtract", "project", "concat",
})

_TOKEN_RE = re.compile(r"""
    (?:\s+|;[^\n]*)       # whitespace and line comments — skip
    |([()[\]'])           # punctuation
    |([+\-])              # sign
    |([0-9]+)             # integer
    |([^\W\d_][^\W_]*\??) # name, keyword, or operator (Unicode letters + optional ?)
    |(.)                  # unexpected character — error
""", re.VERBOSE)


class ParseError(Exception):
    pass


def parse(expr: str) -> ast.Expr:
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    node = parser.parse_expr()
    if parser.peek() is not None:
        raise ParseError(f"Unexpected token after expression: {parser.peek()!r}")
    return node


def _tokenize(text: str) -> list[str]:
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if tok:
            tokens.append(tok)
        elif m.group(5):
            raise ParseError(f"Unexpected character: {m.group(5)!r}")
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
            raise ParseError(f"Expected {value!r}, got {tok!r}")
        return self.consume()

    def parse_expr(self) -> ast.Expr:
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of input")
        if tok == "(":
            return self._parse_operation()
        if tok == "[":
            return self._parse_bracket()
        if tok == "'":
            return self._parse_symbol()
        if tok == "INR":
            self.consume()
            return ast.Inr()
        if tok == "TRM":
            self.consume()
            return ast.Trm()
        if re.fullmatch(r"[0-9]+", tok):
            self.consume()
            return ast.Integer(int(tok))
        raise ParseError(f"Unexpected token: {tok!r}")

    def _parse_operation(self) -> ast.Expr:
        self.expect("(")
        op = self.peek()
        if op not in _OPERATORS:
            raise ParseError(
                f"Unknown operator: {op!r}. "
                f"Expected one of: {sorted(_OPERATORS)}"
            )
        self.consume()
        args = []
        while self.peek() != ")":
            if self.peek() is None:
                raise ParseError(f"Unclosed '(' for operator '{op}'")
            args.append(self.parse_expr())
        self.expect(")")
        return self._make_node(op, args)

    def _make_node(self, op: str, args: list) -> ast.Expr:
        def check_argc(n: int):
            if len(args) != n:
                raise ParseError(
                    f"'{op}' requires {n} argument(s), got {len(args)}"
                )

        def check_type(i: int, typ: type, label: str):
            if not isinstance(args[i], typ):
                raise ParseError(f"'{op}': argument {i + 1} must be {label}")

        match op:
            case "nth":
                check_argc(2)
                check_type(0, ast.Integer, "an integer index")
                return ast.Nth(index=args[0], sequence=args[1])
            case "in?":
                check_argc(2)
                check_type(1, ast.FeatureSpec, "a feature spec e.g. [+F -G]")
                return ast.InClass(segment=args[0], spec=args[1])
            case "models?":
                check_argc(2)
                check_type(1, ast.NcSequence, "a NC sequence e.g. [[+F] [-G]]")
                return ast.Models(sequence=args[0], nc_seq=args[1])
            case "if":
                check_argc(3)
                return ast.If(cond=args[0], then=args[1], else_=args[2])
            case "unify":
                check_argc(2)
                if isinstance(args[1], (ast.FeatureNames, ast.NcSequence)):
                    raise ParseError(
                        f"'unify': argument 2 must be a feature spec e.g. [+F -G]"
                        f" or a segment expression"
                    )
                return ast.Unify(segment=args[0], features=args[1])
            case "subtract":
                check_argc(2)
                check_type(1, ast.FeatureSpec, "a feature spec e.g. [+F -G]")
                return ast.Subtract(segment=args[0], features=args[1])
            case "project":
                check_argc(2)
                check_type(1, ast.FeatureNames, "a feature name list e.g. [F G]")
                return ast.Project(segment=args[0], names=args[1])
            case "concat":
                if not args:
                    raise ParseError("'concat' requires at least 1 argument")
                return ast.Concat(args=args)

    def _parse_bracket(self) -> ast.FeatureSpec | ast.FeatureNames | ast.NcSequence:
        self.expect("[")
        items = []
        while self.peek() != "]":
            if self.peek() is None:
                raise ParseError("Unclosed '['")
            tok = self.peek()
            if tok in ("+", "-"):
                sign = self.consume()
                name = self.peek()
                if name is None or not re.fullmatch(r"[^\W\d_][^\W_]*", name):
                    raise ParseError(
                        f"Expected feature name after '{sign}', got {name!r}"
                    )
                self.consume()
                items.append(ast.ValuedFeature(sign=sign, name=name))
            elif tok == "[":
                inner = self._parse_bracket()
                if not isinstance(inner, ast.FeatureSpec):
                    raise ParseError(
                        "Nested brackets must contain valued features: [[+F -G] ...]"
                    )
                items.append(inner)
            elif re.fullmatch(r"[^\W\d_][^\W_]*", tok):
                items.append(self.consume())
            else:
                raise ParseError(f"Unexpected token in bracket: {tok!r}")
        self.expect("]")
        return self._classify_bracket(items)

    def _classify_bracket(
        self, items: list
    ) -> ast.FeatureSpec | ast.FeatureNames | ast.NcSequence:
        if not items:
            return ast.FeatureSpec(features=[])
        if all(isinstance(i, ast.ValuedFeature) for i in items):
            return ast.FeatureSpec(features=items)
        if all(isinstance(i, str) for i in items):
            return ast.FeatureNames(names=items)
        if all(isinstance(i, ast.FeatureSpec) for i in items):
            return ast.NcSequence(specs=items)
        raise ParseError(
            "Mixed bracket contents: use [+F -G] for feature specs, "
            "[F G] for feature name lists, or [[+F] [+G]] for NC sequences"
        )

    def _parse_symbol(self) -> ast.Symbol:

        self.expect("'")
        name = self.peek()
        if name is None or not re.fullmatch(r"[^\W\d_][^\W_]*", name):
            raise ParseError(f"Expected segment name after \"'\", got {name!r}")
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
    errors = []

    def check_features(features: list[ast.ValuedFeature]):
        for vf in features:
            if vf.name not in valid_features:
                errors.append(
                    f"Rule '{rule_id}': undefined feature '{vf.name}' in Out expression."
                )

    def walk(n: ast.Expr):
        match n:
            case ast.Nth(index=ast.Integer(value=i), sequence=seq):
                if i < 1:
                    errors.append(
                        f"Rule '{rule_id}': (nth {i} ...) — index must be >= 1."
                    )
                elif isinstance(seq, ast.Inr) and i > inr_len:
                    errors.append(
                        f"Rule '{rule_id}': (nth {i} INR) out of bounds"
                        f" — INR has length {inr_len}."
                    )
                elif isinstance(seq, ast.Trm) and i > trm_len:
                    errors.append(
                        f"Rule '{rule_id}': (nth {i} TRM) out of bounds"
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
                            f"Rule '{rule_id}': undefined feature '{name}' in Out expression."
                        )
                walk(seg)
            case ast.InClass(segment=seg, spec=fs):
                check_features(fs.features)
                walk(seg)
            case ast.Models(sequence=seq, nc_seq=nc):
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

    walk(node)
    return errors
