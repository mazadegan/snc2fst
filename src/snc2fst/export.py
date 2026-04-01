"""Export grammar configurations to LaTeX and Unicode text formats."""

from snc2fst import ast
from snc2fst.models import GrammarConfig, Rule
from snc2fst.types import Segment

# ---------------------------------------------------------------------------
# Subscript helpers
# ---------------------------------------------------------------------------

_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _subscript(n: int) -> str:
    return str(n).translate(_SUBSCRIPT_DIGITS)


# ---------------------------------------------------------------------------
# AST → Unicode text
# ---------------------------------------------------------------------------

def _expr_txt(node: ast.Expr, depth: int = 0) -> str:
    indent = "  " * depth
    match node:
        case ast.Inr():
            return "INR"
        case ast.Trm():
            return "TRM"
        case ast.Slice(start=s, end=e, sequence=ast.Inr()):
            return f"INR[{s}]" if s == e else f"INR[{s}:{e}]"
        case ast.Slice(start=s, end=e, sequence=ast.Trm()):
            return f"TRM[{s}]" if s == e else f"TRM[{s}:{e}]"
        case ast.Symbol(name=name):
            return f"&{name}"
        case ast.FeatureSpec(features=features):
            parts = [f"{f.sign}{f.name}" for f in features]
            return "{" + " ".join(parts) + "}"
        case ast.FeatureNames(names=names):
            return "(" + " ".join(names) + ")"
        case ast.Unify(segment=seg, features=fs):
            return f"(unify {_expr_txt(seg)} {_expr_txt(fs)})"
        case ast.Subtract(segment=seg, features=fs):
            return f"(subtract {_expr_txt(seg)} {_expr_txt(fs)})"
        case ast.Project(segment=seg, names=fn):
            return f"(proj {_expr_txt(seg)} {_expr_txt(fn)})"
        case ast.Concat(args=args):
            return "(" + " ".join(_expr_txt(a) for a in args) + ")"
        case ast.InClass(sequence=seq, nc_seq=ast.NcSequence(specs=specs)):
            nc_parts = " ".join(_expr_txt(s) for s in specs)
            return f"(in? {_expr_txt(seq)} [{nc_parts}])"
        case ast.If(cond=cond, then=then, else_=else_):
            lines = [
                f"{indent}(if {_expr_txt(cond)}",
                f"{indent}    {_expr_txt(then, depth + 1)}",
                f"{indent}    {_expr_txt(else_, depth + 1)})",
            ]
            return "\n".join(lines)
        case _:
            raise ValueError(f"Cannot render node: {node!r}")


# ---------------------------------------------------------------------------
# AST → LaTeX
# ---------------------------------------------------------------------------

def _feature_latex(f: ast.ValuedFeature) -> str:
    return f"{f.sign}\\textsc{{{f.name}}}"


def _expr_latex(node: ast.Expr, depth: int = 0) -> str:
    indent = "    " * depth
    match node:
        case ast.Inr():
            return "\\iota"
        case ast.Trm():
            return "\\tau"
        case ast.Slice(start=s, end=e, sequence=ast.Inr()):
            return f"\\iota_{{{s}}}" if s == e else f"\\iota_{{[{s}:{e}]}}"
        case ast.Slice(start=s, end=e, sequence=ast.Trm()):
            return f"\\tau_{{{s}}}" if s == e else f"\\tau_{{[{s}:{e}]}}"
        case ast.Symbol(name=name):
            return f"\\text{{{name}}}"
        case ast.FeatureSpec(features=features):
            parts = ", ".join(_feature_latex(f) for f in features)
            return "\\{" + parts + "\\}"
        case ast.FeatureNames(names=names):
            parts = ", ".join(f"\\textsc{{{n}}}" for n in names)
            return "\\{" + parts + "\\}"
        case ast.Unify(segment=seg, features=fs):
            return f"({_expr_latex(seg)} \\sqcup {_expr_latex(fs)})"
        case ast.Subtract(segment=seg, features=fs):
            return f"({_expr_latex(seg)} \\setminus {_expr_latex(fs)})"
        case ast.Project(segment=seg, names=fn):
            return f"({_expr_latex(seg)} \\upharpoonright {_expr_latex(fn)})"
        case ast.Concat(args=args):
            return " \\cdot ".join(_expr_latex(a) for a in args)
        case ast.InClass(sequence=seq, nc_seq=ast.NcSequence(specs=specs)):
            nc_parts = ", ".join(_expr_latex(s) for s in specs)
            return f"{_expr_latex(seq)} \\in \\mathcal{{N}}(\\langle {nc_parts} \\rangle)"
        case ast.If(cond=cond, then=then, else_=else_):
            if depth == 0:
                lines = [
                    "\\begin{cases}",
                    f"  {_expr_latex(then, depth + 1)} & \\text{{if }} {_expr_latex(cond)} \\\\",
                    f"  {_expr_latex(else_, depth + 1)} & \\text{{otherwise}}",
                    "\\end{cases}",
                ]
                return "\n".join(lines)
            else:
                c = _expr_latex(cond)
                t = _expr_latex(then, depth + 1)
                e = _expr_latex(else_, depth + 1)
                return f"({c} \\mathbin{{?}} {t} \\mathbin{{:}} {e})"
        case _:
            raise ValueError(f"Cannot render node: {node!r}")


# ---------------------------------------------------------------------------
# Rule rendering
# ---------------------------------------------------------------------------

def _nc_seq_txt(nc_seq: list[list[tuple[str, str]]]) -> str:
    """Render a parsed Inr/Trm (list of FeatureSpec-like tuples) as Unicode."""
    parts = []
    for spec in nc_seq:
        if not spec:
            parts.append("[∅]")
        else:
            inner = " ".join(f"{sign}{name}" for sign, name in spec)
            parts.append("[{" + inner + "}]")
    return "⟨" + " ".join(parts) + "⟩"


def _nc_seq_latex(nc_seq: list[list[tuple[str, str]]]) -> str:
    parts = []
    for spec in nc_seq:
        if not spec:
            parts.append("\\mathcal{N}(\\emptyset)")
        else:
            inner = ", ".join(f"{sign}\\textsc{{{name}}}" for sign, name in spec)
            parts.append(f"\\mathcal{{N}}(\\{{{inner}\\}})")
    return "\\langle " + ", ".join(parts) + " \\rangle"


def _rule_txt(rule: Rule, out_ast: ast.Expr) -> str:
    lines = [f"Rule {rule.Id}"]
    lines.append(f"  Dir: {rule.Dir}")
    lines.append(f"  Inr: {_nc_seq_txt(rule.Inr)}")
    lines.append(f"  Trm: {_nc_seq_txt(rule.Trm)}")
    out_rendered = _expr_txt(out_ast)
    if "\n" in out_rendered:
        out_indented = "\n".join("    " + l for l in out_rendered.splitlines())
        lines.append(f"  Out:\n{out_indented}")
    else:
        lines.append(f"  Out: {out_rendered}")
    return "\n".join(lines)


def _rule_latex(rule: Rule, out_ast: ast.Expr) -> str:
    dir_str = "\\textsc{Right}" if rule.Dir == "R" else "\\textsc{Left}"
    inr_str = _nc_seq_latex(rule.Inr)
    trm_str = _nc_seq_latex(rule.Trm)
    out_str = _expr_latex(out_ast, depth=0)
    lines = [
        f"% {rule.Id}",
        f"\\begin{{align*}}",
        f"  \\textsc{{Inr}} &= {inr_str} \\\\",
        f"  \\textsc{{Trm}} &= {trm_str} \\\\",
        f"  \\textsc{{Dir}} &= {dir_str} \\\\",
        f"  \\textsc{{Out}} &= \\lambda\\iota.\\,\\lambda\\tau.\\, {out_str}",
        f"\\end{{align*}}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alphabet rendering
# ---------------------------------------------------------------------------

def _alphabet_txt(alphabet: dict[str, Segment]) -> str:
    if not alphabet:
        return ""
    segments = list(alphabet.keys())
    features = list(next(iter(alphabet.values())).keys())

    col_width = max(len(s) for s in segments + [""])
    feat_width = max(len(f) for f in features)

    header = " " * (feat_width + 2) + "  ".join(s.ljust(col_width) for s in segments)
    lines = [header, "-" * len(header)]
    for feat in features:
        vals = "  ".join(alphabet[s].get(feat, " ").center(col_width) for s in segments)
        lines.append(f"{feat.ljust(feat_width)}  {vals}")
    return "\n".join(lines)


def _alphabet_latex(alphabet: dict[str, Segment]) -> str:
    if not alphabet:
        return ""
    segments = list(alphabet.keys())
    features = list(next(iter(alphabet.values())).keys())

    col_spec = "r" + "c" * len(segments)
    seg_header = " & ".join(f"\\text{{{s}}}" for s in segments)

    lines = [
        f"\\begin{{tabular}}{{{col_spec}}}",
        f"  & {seg_header} \\\\",
        "  \\hline",
    ]
    for feat in features:
        vals = " & ".join(alphabet[s].get(feat, "") for s in segments)
        lines.append(f"  \\textsc{{{feat}}} & {vals} \\\\")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level export functions
# ---------------------------------------------------------------------------

def export_txt(config: GrammarConfig, alphabet: dict[str, Segment]) -> str:
    from snc2fst import dsl
    sections = ["=== Alphabet ===", "", _alphabet_txt(alphabet)]
    for rule in config.rules:
        out_ast = dsl.parse(rule.Out)
        sections += ["", f"=== {rule.Id} ===", "", _rule_txt(rule, out_ast)]
    return "\n".join(sections)


_LATEX_PREAMBLE = """\
% Required packages:
%   \\usepackage{amsmath}   % \\sqcup, \\setminus, \\models, \\langle, \\rangle, align*, cases environments
%   \\usepackage{amssymb}   % \\mathcal, \\upharpoonright
%   \\usepackage{booktabs}  % optional, for nicer alphabet table rules"""


def export_latex(config: GrammarConfig, alphabet: dict[str, Segment]) -> str:
    from snc2fst import dsl
    sections = [_LATEX_PREAMBLE, "", _alphabet_latex(alphabet)]
    for rule in config.rules:
        out_ast = dsl.parse(rule.Out)
        sections += ["", _rule_latex(rule, out_ast)]
    return "\n".join(sections)
