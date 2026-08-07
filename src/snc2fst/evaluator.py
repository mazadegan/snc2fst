from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import logical_phonology as lp

from snc2fst import dsl_ast as ast
from snc2fst.errors import EvalError
from snc2fst.models import Rule
from snc2fst.wellformed import check_wellformed

# ---------------------------------------------------------------------------
# Direction-parameterized scanning primitives
# ---------------------------------------------------------------------------
#
# Evaluation scans the word *against* Dir: right-to-left for Dir=R, left-to-
# right for Dir=L.  Rather than reversing the word onto a single machine — a
# normalization that is unsound, since a Trm-window is anchored at its left
# end under both directions — we keep buffers in word order throughout and let
# Dir choose only which end is "new" and which is "stale".
#
#                     Dir = R              Dir = L
#   scan order        i = l-1 ... 0        i = 0 ... l-1
#   push(C, a)        a . C                C . a
#   stale(C)          last(C)              first(C)
#   drop_stale(C)     init(C)              tail(C)
#   emit(O, c)        prepend c to O       append c to O


@dataclass
class _Ring:
    """A bounded buffer of already-scanned segments, held in word order.

    ``right`` is True for Dir=R.  The "stale" end is the one holding the
    earliest-scanned segment, which — because the scan runs against Dir — is
    always the Dir-side end.
    """

    right: bool
    items: deque[lp.Segment] = field(default_factory=deque)

    def push(self, seg: lp.Segment) -> None:
        if self.right:
            self.items.appendleft(seg)
        else:
            self.items.append(seg)

    def stale(self) -> lp.Segment:
        return self.items[-1] if self.right else self.items[0]

    def drop_stale(self) -> None:
        if self.right:
            self.items.pop()
        else:
            self.items.popleft()

    def clear(self) -> None:
        self.items.clear()

    def word(self, fs: lp.FeatureSystem) -> lp.Word:
        return fs.word(list(self.items))

    def __len__(self) -> int:
        return len(self.items)


class _Sink:
    """Output accumulator: emissions land at the anti-scan end.

    Because the scan runs against Dir, each newly emitted chunk belongs
    further along in word order than everything emitted so far, so emissions
    concatenate in increasing position order.
    """

    def __init__(self, right: bool) -> None:
        self.right = right
        self.items: deque[lp.Segment] = deque()

    def emit(self, segs: Sequence[lp.Segment]) -> None:
        if self.right:
            self.items.extendleft(reversed(segs))
        else:
            self.items.extend(segs)

    def word(self, fs: lp.FeatureSystem) -> lp.Word:
        return fs.word(list(self.items))


def _scan_order(length: int, right: bool) -> Iterable[int]:
    """Indices in scan order — against Dir."""
    return range(length - 1, -1, -1) if right else range(length)


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
) -> lp.Word | bool:
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
            return fs.word([inv[name]])
        case ast.FeatureSpec() as fs_node:
            # Bare feature spec in Concat = epenthetic underspecified segment
            return fs.word([_spec_to_segment(fs_node, fs)])
        case ast.Unify(segment=seg_node, features=features_node):
            seg = _as_segment(evaluate(seg_node, inr, trm, fs, inv), "unify")
            if isinstance(features_node, ast.FeatureSpec):
                other = _spec_to_segment(features_node, fs)
            else:
                other = _as_segment(
                    evaluate(features_node, inr, trm, fs, inv), "unify"
                )
            return fs.word([seg.unify(other)])
        case ast.Subtract(segment=seg_node, features=features_node):
            seg = _as_segment(
                evaluate(seg_node, inr, trm, fs, inv), "subtract"
            )
            return fs.word([seg.subtract(_spec_to_segment(features_node, fs))])
        case ast.Project(segment=seg_node, names=fn):
            seg = _as_segment(evaluate(seg_node, inr, trm, fs, inv), "proj")
            return fs.word([seg.project(frozenset(fn.names))])
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


def _check_boundary_positions(
    word: lp.Word, rule_id: str, fs: lp.FeatureSystem
) -> None:
    """Raise EvalError if BOS/EOS appear at illegal positions in word."""
    bos_count = 0
    eos_count = 0
    for i, seg in enumerate(word):
        if seg == fs.BOS:
            bos_count += 1
            if i != 0:
                raise EvalError(
                    f"Rule '{rule_id}': BOS boundary ended up at position {i + 1} "  # noqa: E501
                    "(must be at position 1)."
                )
        if seg == fs.EOS:
            eos_count += 1
            if i != len(word) - 1:
                raise EvalError(
                    f"Rule '{rule_id}': EOS boundary ended up at position {i + 1} "  # noqa: E501
                    f"(must be at position {len(word)})."
                )
    if bos_count > 1:
        raise EvalError(
            f"Rule '{rule_id}': multiple BOS boundaries in output."
        )
    if eos_count > 1:
        raise EvalError(
            f"Rule '{rule_id}': multiple EOS boundaries in output."
        )


def _eval_out(
    rule: Rule,
    out_ast: ast.Expr,
    target: lp.Word,
    trigger: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
) -> list[lp.Segment]:
    """Evaluate Out on a matched (INR, TRM) pair, as a list of segments."""
    try:
        raw = evaluate(out_ast, target, trigger, fs, inv)
    except EvalError as e:
        raise EvalError(f"Rule '{rule.Id}': {e}") from e
    if isinstance(raw, bool):
        raise EvalError(
            f"Rule '{rule.Id}': Out expression evaluated to a boolean"
        )
    return list(raw)


def eval_cnd(
    rule: Rule,
    cnd_ast: ast.Expr | None,
    target: lp.Word,
    trigger: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
) -> bool:
    """Evaluate a rule's licensing condition on a matched (INR, TRM) pair.

    A rule with no Cnd licenses every INR-match, so this returns True.
    """
    if cnd_ast is None:
        return True
    try:
        raw = evaluate(cnd_ast, target, trigger, fs, inv)
    except EvalError as e:
        raise EvalError(f"Rule '{rule.Id}': {e}") from e
    if not isinstance(raw, bool):
        raise EvalError(
            f"Rule '{rule.Id}': Cnd expression did not evaluate to a "
            "boolean. Use a condition such as (in? TRM [{+F}])."
        )
    return raw


def apply_rule(
    rule: Rule,
    out_ast: ast.Expr,
    word: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    cnd_ast: ast.Expr | None = None,
) -> lp.Word:
    """Apply a single S&C rule to a word, returning the transformed word.

    A deterministic single pass over the word, run *against* ``Dir``, keeping
    three pieces of bounded state:

    * ``B`` — a buffer of the last ``m`` scanned segments, the candidate
      INR-window.  On a match the rule fires and ``B`` is cleared, so the
      window is consumed whole; otherwise its stale segment is emitted and
      ``B`` slides by one.  That reset is the whole of the overlap policy:
      among licensed windows that overlap each other, the Dir-most fires.
    * ``T`` — the same for the candidate TRM-window.  Unlike ``B`` it never
      resets on a match, since a terminator is not consumed.
    * ``p`` — the *content* of the nearest TRM-window found so far, or None
      for "no terminator yet".  Every TRM-match overwrites it, which is what
      makes a terminator block rather than be skipped past.

    ``p`` is read at the firing test *before* the current segment is latched
    into it, which is what stops a position from licensing itself.

    ``cnd_ast``, if given, is the rule's licensing condition: an INR-match
    whose condition is false slides rather than firing, so its segments stay
    available to a later overlapping window.

    The word is bracketed with BOS/EOS pseudo-segments before scanning and
    stripped after, so rules may condition on word edges.
    """
    check_wellformed(rule, EvalError)

    inr_ncs = rule.inr_as_ncs(fs)
    trm_ncs = rule.trm_as_ncs(fs)
    m, n = len(inr_ncs), len(trm_ncs)

    scanned = fs.add_boundaries(word)
    right = rule.Dir == "R"
    target_buf, trigger_buf = _Ring(right), _Ring(right)
    out = _Sink(right)
    # With no TRM to find, every position is trivially licensed by the empty
    # window — which is also what Out receives as its TRM argument.
    pointer: lp.Word | None = fs.word([]) if n == 0 else None

    for i in _scan_order(len(scanned), right):
        seg = scanned[i]

        target_buf.push(seg)
        if len(target_buf) == m:
            target = target_buf.word(fs)
            if (
                pointer is not None
                and target in inr_ncs
                and eval_cnd(rule, cnd_ast, target, pointer, fs, inv)
            ):
                out.emit(
                    _eval_out(rule, out_ast, target, pointer, fs, inv)
                )
                target_buf.clear()  # fire: consume the whole window
            else:
                out.emit([target_buf.stale()])
                target_buf.drop_stale()  # slide by one

        # Latch strictly after resolving the target buffer, so the pointer
        # read above cannot already include a TRM-window starting here.
        if n:
            trigger_buf.push(seg)
            if len(trigger_buf) == n:
                candidate = trigger_buf.word(fs)
                if candidate in trm_ncs:
                    pointer = candidate
                trigger_buf.drop_stale()

    out.emit(list(target_buf.items))  # flush the residual, len < m

    result = out.word(fs)
    _check_boundary_positions(result, rule.Id, fs)
    return fs.remove_boundaries(result)
