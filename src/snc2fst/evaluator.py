from snc2fst import ast, operations
from snc2fst.alphabet import BOS_SEGMENT, EOS_SEGMENT
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
            if isinstance(fs, ast.FeatureSpec):
                spec = _to_spec(fs)
            else:
                other = evaluate(fs, inr, trm, alphabet)
                spec = [(v, f) for f, v in other.items()]
            return operations.unify(seg, spec)
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


def _find_trigger(
    word: Word,
    trm: list,
    anchor: int,
    rightward: bool,
) -> "Word | None":
    """Search word for the nearest window of len(trm) that models trm.

    For rightward search, scans from anchor toward the end of the word.
    For leftward search, scans from anchor toward the beginning.
    Returns the first matching window found, or None.
    """
    n = len(trm)
    if n == 0:
        return []
    if rightward:
        for j in range(anchor, len(word) - n + 1):
            candidate = word[j : j + n]
            if operations.models(candidate, trm):
                return list(candidate)
    else:
        for j in range(anchor, -1, -1):
            candidate = word[j : j + n]
            if operations.models(candidate, trm):
                return list(candidate)
    return None


def _check_boundary_positions(word: Word, rule_id: str) -> None:
    """Raise EvalError if BOS/EOS appear at illegal positions in word."""
    for i, seg in enumerate(word):
        if seg == BOS_SEGMENT and i != 0:
            raise EvalError(
                f"Rule '{rule_id}': BOS boundary ended up at position {i + 1} "
                "(must be at position 1)."
            )
        if seg == EOS_SEGMENT and i != len(word) - 1:
            raise EvalError(
                f"Rule '{rule_id}': EOS boundary ended up at position {i + 1} "
                f"(must be at position {len(word)})."
            )
    bos_count = sum(1 for s in word if s == BOS_SEGMENT)
    eos_count = sum(1 for s in word if s == EOS_SEGMENT)
    if bos_count > 1:
        raise EvalError(f"Rule '{rule_id}': multiple BOS boundaries in output.")
    if eos_count > 1:
        raise EvalError(f"Rule '{rule_id}': multiple EOS boundaries in output.")


def apply_rule(
    rule: Rule,
    out_ast: ast.Expr,
    word: Word,
    alphabet: dict[str, Segment],
) -> Word:
    """Apply a single S&C rule to a word, returning the transformed word.

    The word is bracketed with BOS/EOS pseudo-segments before processing and
    stripped after. Scans left-to-right for non-overlapping target windows
    (INR). For each target, searches in direction Dir for the nearest window
    that models TRM (which may be non-adjacent). When found, OUT is evaluated
    and the target is replaced.
    """
    from snc2fst.alphabet import bracket_word, strip_boundaries

    m = len(rule.Inr)  # target window length
    n = len(rule.Trm)  # trigger window length
    result = bracket_word(word)
    i = 0
    while i <= len(result) - m:
        target = result[i : i + m]
        if not operations.models(target, rule.Inr):
            i += 1
            continue

        if rule.Dir == "R":
            trigger = _find_trigger(result, rule.Trm, i + m, rightward=True)
        else:
            trigger = _find_trigger(result, rule.Trm, i - n, rightward=False)

        if trigger is None:
            i += 1
            continue

        try:
            raw = evaluate(out_ast, target, trigger, alphabet)
        except EvalError as e:
            raise EvalError(f"Rule '{rule.Id}': {e}") from e
        out: Word = [raw] if isinstance(raw, dict) else list(raw)  # type: ignore[arg-type]
        result[i : i + m] = out
        i += len(out)

    _check_boundary_positions(result, rule.Id)
    return strip_boundaries(result)
