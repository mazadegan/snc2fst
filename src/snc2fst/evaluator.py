import logical_phonology as lp

from snc2fst import dsl_ast as ast
from snc2fst.errors import EvalError


def _as_segment(val: lp.Word | lp.Segment | bool, op_name: str) -> lp.Segment:
    """Extract a single segment from a segment or length-1 word.

    Args:
        val: A Segment or Word to extract from.
        op_name: The operator name, used in error messages.

    Raises:
        EvalError: If val is a Word of length != 1.
    """
    if isinstance(val, bool):
        raise EvalError(f"'{op_name}' expected a segment, got a boolean")
    if isinstance(val, lp.Segment):
        return val
    if len(val) == 1:
        return val[0]
    raise EvalError(
        f"'{op_name}' expected a single segment, got a word of length {len(val)}"  # noqa: E501
    )


def _as_word(
    val: lp.Word | lp.Segment | bool,
    op_name: str,
    fs: lp.FeatureSystem,
) -> lp.Word:
    """
    Convert a segment or word to a Word, raising EvalError on bool.

    Args:
        val: The value to convert.
        op_name: The operator name, used in error messages.
        fs: The FeatureSystem used to wrap a single Segment into a Word.

    Raises:
        EvalError: If val is a boolean.
    """
    if isinstance(val, bool):
        raise EvalError(
            f"'{op_name}' expected a word or segment, got a boolean"
        )
    if isinstance(val, lp.Segment):
        return fs.word([val])
    return val


def _spec_to_segment(
    spec: ast.FeatureSpec, fs: lp.FeatureSystem
) -> lp.Segment:
    """Convert a DSL FeatureSpec AST node into an LP Segment.

    Args:
        spec: A FeatureSpec AST node containing valued features.
        fs: The FeatureSystem to construct the segment from.

    Returns:
        A new Segment with the features specified in the FeatureSpec.
    """
    return fs.segment(
        {vf.name: lp.FeatureValue.from_str(vf.sign) for vf in spec.features}
    )


def _spec_to_natural_class(
    spec: ast.FeatureSpec, fs: lp.FeatureSystem
) -> lp.NaturalClass:
    """Convert a DSL FeatureSpec AST node into an LP NaturalClass."""
    return fs.natural_class(
        {vf.name: lp.FeatureValue.from_str(vf.sign) for vf in spec.features}
    )


def evaluate(
    node: ast.Expr,
    inr: lp.Word,
    trm: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
) -> lp.Word | lp.Segment | bool:
    """Evaluate a DSL expression with bound INR and TRM windows.

    Args:
        node: The AST node to evaluate.
        inr: The initiator window — the matched target substring.
        trm: The terminator window — the matched trigger substring.
        fs: The feature system for constructing segments and natural classes.
        inv: The inventory for looking up named segments.

    Returns:
        A Word, Segment, or bool depending on the expression type.

    Raises:
        EvalError: If evaluation fails due to type mismatches or unknown
            symbols.
    """
    match node:
        case ast.Inr():
            return inr
        case ast.Trm():
            return trm
        case ast.Slice(start=s, end=e, sequence=seq):
            word = evaluate(seq, inr, trm, fs, inv)
            assert isinstance(word, lp.Word)
            return word[s - 1 : e]  # 1-based, inclusive; returns lp.Word
        case ast.Symbol(name=name):
            if name not in inv:
                raise EvalError(f"Unknown segment symbol: '{name}'")
            return inv[name]
        case ast.FeatureSpec() as fs_node:
            # Bare feature spec in Concat = epenthetic underspecified segment
            return _spec_to_segment(fs_node, fs)
        case ast.Unify(segment=seg_node, features=features_node):
            seg = _as_segment(evaluate(seg_node, inr, trm, fs, inv), "unify")
            if isinstance(features_node, ast.FeatureSpec):
                other = _spec_to_segment(features_node, fs)
            else:
                other = _as_segment(
                    evaluate(features_node, inr, trm, fs, inv), "unify"
                )
            return seg.unify(other)
        case ast.Subtract(segment=seg_node, features=features_node):
            seg = _as_segment(
                evaluate(seg_node, inr, trm, fs, inv), "subtract"
            )
            return seg.subtract(_spec_to_segment(features_node, fs))
        case ast.Project(segment=seg_node, names=fn):
            seg = _as_segment(evaluate(seg_node, inr, trm, fs, inv), "proj")
            return seg.project(frozenset(fn.names))
        case ast.Concat(args=args):
            result: lp.Word = fs.word([])
            for arg in args:
                result = result + _as_word(
                    evaluate(arg, inr, trm, fs, inv), "concat", fs
                )
            return result
        case ast.InClass(sequence=seq_node, nc_sequence=nc_seq):
            word = _as_word(evaluate(seq_node, inr, trm, fs, inv), "in?", fs)
            ncs = fs.natural_class_sequence(
                [_spec_to_natural_class(spec, fs) for spec in nc_seq.specs]
            )
            return word in ncs
        case ast.If(cond=cond_node, then=then_node, else_=else_node):
            if evaluate(cond_node, inr, trm, fs, inv):
                return evaluate(then_node, inr, trm, fs, inv)
            else:
                return evaluate(else_node, inr, trm, fs, inv)
        case _:
            raise EvalError(f"Cannot evaluate node: {node!r}")
