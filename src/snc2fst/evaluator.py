from snc2fst import ast, operations
from snc2fst.models import Rule
from snc2fst.types import FeatureSpec, FeatureSpecSequence, Segment, Word


class EvalError(Exception):
    pass


def _to_spec(fs: ast.FeatureSpec) -> FeatureSpec:
    return [(vf.sign, vf.name) for vf in fs.features]


def _to_spec_seq(nc_seq: ast.NcSequence) -> FeatureSpecSequence:
    return [_to_spec(spec) for spec in nc_seq.specs]


def evaluate(
    node: ast.Expr,
    inr: Word,
    trm: Word,
    alphabet: dict[str, Segment],
) -> "Word | Segment | bool":
    """Evaluate a DSL expression with bound INR and TRM windows."""
    match node:
        case ast.Inr():
            return list(inr)
        case ast.Trm():
            return list(trm)
        case ast.Nth(index=ast.Integer(value=i), sequence=seq):
            word = evaluate(seq, inr, trm, alphabet)
            return word[i - 1]  # 1-based indexing
        case ast.Symbol(name=name):
            if name not in alphabet:
                raise EvalError(f"Unknown segment symbol: '{name}'")
            return dict(alphabet[name])
        case ast.FeatureSpec() as fs:
            # Bare feature spec in Concat = epenthetic underspecified segment
            return {name: sign for sign, name in _to_spec(fs)}
        case ast.Unify(segment=seg_node, features=fs):
            seg = evaluate(seg_node, inr, trm, alphabet)
            return operations.unify(seg, _to_spec(fs))
        case ast.Subtract(segment=seg_node, features=fs):
            seg = evaluate(seg_node, inr, trm, alphabet)
            return operations.subtract(seg, _to_spec(fs))
        case ast.Project(segment=seg_node, names=fn):
            seg = evaluate(seg_node, inr, trm, alphabet)
            return operations.project(seg, fn.names)
        case ast.Concat(args=args):
            result: Word = []
            for arg in args:
                val = evaluate(arg, inr, trm, alphabet)
                if isinstance(val, list):
                    result.extend(val)
                else:
                    result.append(val)
            return result
        case ast.InClass(segment=seg_node, spec=spec):
            seg = evaluate(seg_node, inr, trm, alphabet)
            return operations.in_class(seg, _to_spec(spec))
        case ast.Models(sequence=seq_node, nc_seq=nc_seq):
            word = evaluate(seq_node, inr, trm, alphabet)
            return operations.models(word, _to_spec_seq(nc_seq))
        case ast.If(cond=cond_node, then=then_node, else_=else_node):
            if evaluate(cond_node, inr, trm, alphabet):
                return evaluate(then_node, inr, trm, alphabet)
            else:
                return evaluate(else_node, inr, trm, alphabet)
        case _:
            raise EvalError(f"Cannot evaluate node: {node!r}")


def apply_rule(
    rule: Rule,
    out_ast: ast.Expr,
    word: Word,
    alphabet: dict[str, Segment],
) -> Word:
    """Apply a single S&C rule to a word, returning the transformed word.

    Scans left-to-right for non-overlapping target windows (INR).  For each
    target, the trigger window (TRM) is checked on the side indicated by Dir:
      Dir="R" — trigger immediately to the right of the target
      Dir="L" — trigger immediately to the left of the target
    When both windows match, OUT is evaluated and the target is replaced.
    """
    m = len(rule.Inr)  # target window length
    n = len(rule.Trm)  # trigger window length
    result = list(word)
    i = 0
    while i <= len(result) - m:
        target = result[i : i + m]
        if not operations.models(target, rule.Inr):
            i += 1
            continue

        if rule.Dir == "R":
            trm_start = i + m
            trm_end = trm_start + n
            if trm_end > len(result):
                i += 1
                continue
            trigger = result[trm_start:trm_end]
        else:  # "L"
            trm_start = i - n
            if trm_start < 0:
                i += 1
                continue
            trigger = result[trm_start:i]

        if not operations.models(trigger, rule.Trm):
            i += 1
            continue

        out: Word = evaluate(out_ast, target, trigger, alphabet)  # type: ignore[assignment]
        result[i : i + m] = out
        i += len(out)

    return result
