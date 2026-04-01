"""Recursive descent parser for the S&C DSL.

Public API:
    parse(expr: str) -> ast.Expr
    collect_errors(...) -> list[str]
    ParseError
"""

import re
from snc2fst import ast

_OPERATORS = frozenset({
    "in?", "if",
    "unify", "subtract", "proj",
})

_TOKEN_RE = re.compile(r"""
    (?:\s+|;[^\n]*)       # whitespace and line comments — skip
    |([()[\]{}&,:])       # punctuation
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
        if re.fullmatch(r"[0-9]+", tok):
            self.consume()
            return ast.Integer(int(tok))
        raise ParseError(f"Unexpected token: {tok!r}")

    def _maybe_index(self, seq: ast.Expr) -> ast.Expr:
        """Parse INR[N], INR[N:M], or bare INR."""
        if self.peek() != "[":
            return seq
        saved = self.pos
        self.consume()  # consume '['
        tok = self.peek()
        if tok is not None and re.fullmatch(r"[0-9]+", tok):
            start = int(self.consume())
            if self.peek() == ":":
                self.consume()  # consume ':'
                tok2 = self.peek()
                if tok2 is None or not re.fullmatch(r"[0-9]+", tok2):
                    raise ParseError(f"Expected integer after ':', got {tok2!r}")
                end = int(self.consume())
            else:
                end = start  # INR[N] is sugar for INR[N:N]
            self.expect("]")
            return ast.Slice(start, end, seq)
        # Not an index — restore position and return bare seq
        self.pos = saved
        return seq

    def _parse_paren(self) -> ast.Expr:
        self.expect("(")
        op = self.peek()
        if op in _OPERATORS:
            self.consume()
            args = []
            if op == "proj":
                # (proj SEGMENT (F G ...))
                if self.peek() is None or self.peek() == ")":
                    raise ParseError("'proj' requires 2 arguments, got 0")
                args.append(self.parse_expr())
                if self.peek() != "(":
                    raise ParseError(
                        f"'proj': argument 2 must be a feature name list e.g. (Voice Back)"
                    )
                args.append(self._parse_proj_names())
            else:
                while self.peek() != ")":
                    if self.peek() is None:
                        raise ParseError(f"Unclosed '(' for operator '{op}'")
                    args.append(self.parse_expr())
            self.expect(")")
            return self._make_node(op, args)
        # Bare parens = implicit concat
        args = []
        while self.peek() != ")":
            if self.peek() is None:
                raise ParseError("Unclosed '(' in implicit concat sequence")
            args.append(self.parse_expr())
        self.expect(")")
        if not args:
            raise ParseError("Empty parentheses — implicit concat requires at least 1 element")
        return ast.Concat(args=args)

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
            case "in?":
                check_argc(2)
                check_type(1, ast.NcSequence, "a natural class sequence e.g. [{+F -G}]")
                return ast.InClass(sequence=args[0], nc_seq=args[1])
            case "if":
                check_argc(3)
                return ast.If(cond=args[0], then=args[1], else_=args[2])
            case "unify":
                check_argc(2)
                if isinstance(args[1], (ast.FeatureNames, ast.NcSequence)):
                    raise ParseError(
                        "'unify': argument 2 must be a feature bundle e.g. {+F -G}"
                        " or a segment expression"
                    )
                return ast.Unify(segment=args[0], features=args[1])
            case "subtract":
                check_argc(2)
                check_type(1, ast.FeatureSpec, "a feature bundle e.g. {+F -G}")
                return ast.Subtract(segment=args[0], features=args[1])
            case "proj":
                check_argc(2)
                check_type(1, ast.FeatureNames, "a feature name list e.g. (F G)")
                return ast.Project(segment=args[0], names=args[1])

    def _parse_feature_bundle(self) -> ast.FeatureSpec:
        """Parse {+F -G ...} — a feature bundle."""
        self.expect("{")
        features = []
        while self.peek() != "}":
            if self.peek() is None:
                raise ParseError("Unclosed '{'")
            tok = self.peek()
            if tok == ",":
                self.consume()
                continue
            if tok not in ("+", "-"):
                raise ParseError(
                    f"Expected '+' or '-' in feature bundle, got {tok!r}"
                )
            sign = self.consume()
            name = self.peek()
            if name is None or not re.fullmatch(r"[^\W\d_][^\W_]*", name):
                raise ParseError(
                    f"Expected feature name after '{sign}', got {name!r}"
                )
            self.consume()
            features.append(ast.ValuedFeature(sign=sign, name=name))
        self.expect("}")
        return ast.FeatureSpec(features=features)

    def _parse_bracket(self) -> ast.NcSequence:
        """Parse [{+F} {-G} ...] — a natural class sequence."""
        self.expect("[")
        specs = []
        while self.peek() != "]":
            if self.peek() is None:
                raise ParseError("Unclosed '['")
            tok = self.peek()
            if tok == ",":
                self.consume()
                continue
            if tok != "{":
                raise ParseError(
                    f"Expected '{{' inside natural class sequence, got {tok!r}. "
                    "Use [{+F -G}] for a natural class."
                )
            specs.append(self._parse_feature_bundle())
        self.expect("]")
        return ast.NcSequence(specs=specs)

    def _parse_proj_names(self) -> ast.FeatureNames:
        """Parse (F G ...) — a list of bare feature names for proj."""
        self.expect("(")
        names = []
        while self.peek() != ")":
            if self.peek() is None:
                raise ParseError("Unclosed '(' in feature name list")
            tok = self.peek()
            if not re.fullmatch(r"[^\W\d_][^\W_]*", tok):
                raise ParseError(
                    f"Expected feature name in proj list, got {tok!r}"
                )
            names.append(self.consume())
        self.expect(")")
        if not names:
            raise ParseError("proj feature name list cannot be empty")
        return ast.FeatureNames(names=names)

    def _parse_symbol(self) -> ast.Symbol:
        self.expect("&")
        name = self.peek()
        if name is None or not re.fullmatch(r"[^\W\d_][^\W_]*", name):
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
    errors = []

    def check_features(features: list[ast.ValuedFeature]):
        for vf in features:
            if vf.name not in valid_features:
                errors.append(
                    f"Rule '{rule_id}': undefined feature '{vf.name}' in Out expression."
                )

    def walk(n: ast.Expr):
        match n:
            case ast.Slice(start=s, end=e, sequence=seq):
                if s < 1 or e < 1:
                    errors.append(
                        f"Rule '{rule_id}': INR/TRM[{s}:{e}] — indices must be >= 1."
                    )
                elif s > e:
                    errors.append(
                        f"Rule '{rule_id}': INR/TRM[{s}:{e}] — start must be <= end."
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
                            f"Rule '{rule_id}': undefined feature '{name}' in Out expression."
                        )
                walk(seg)
            case ast.InClass(sequence=seq, nc_seq=nc):
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
