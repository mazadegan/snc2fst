"""Behavioural quotient of the terminator pointer.

Compiling a rule to an FST means tabulating the evaluator's control state,
which includes ``p`` — the content of the nearest licensed TRM-window.  Stored
literally, ``p`` ranges over all of ``L(Trm)``, and since the TRM buffer is
also part of the state, the configuration count grows as
``|Sigma|^(m + 2n - 2)``: ``n`` costs twice what ``m`` does.  That is
infeasible past ``n = 2`` on a realistic inventory.

But ``p`` is never inspected directly.  It reaches the outside world only as
the TRM argument of ``Out`` and ``Cnd``.  So two TRM-windows are
interchangeable — the machine cannot tell them apart at any future point — iff
they license the same INR-windows and produce the same output on each:

    p ~ p'  iff  for every w in L(Inr), Cnd(w, p) == Cnd(w, p'),
                 and wherever that holds, Out(w, p) == Out(w, p')

Keying states on that equivalence class instead of the window itself is exact
(it never merges two windows the rule could distinguish) and often collapses
``L(Trm)`` drastically: a rule reading TRM only through ``proj`` sees just the
projected features, and a rule ignoring TRM entirely collapses to one class.

This module has no pynini dependency, so it is usable from the evaluator side
and from ``validate`` in an install without it.
"""

from __future__ import annotations

from dataclasses import dataclass

import logical_phonology as lp

from snc2fst import dsl_ast as ast
from snc2fst.errors import CompileError
from snc2fst.evaluator import eval_cnd, evaluate
from snc2fst.models import Rule

# One entry per INR-window, in a fixed order: None where Cnd rejects the pair,
# otherwise the canonical form of each segment Out produces.  Canonical forms
# (str(seg)) are used rather than inventory names because Out may legitimately
# produce a segment the inventory does not yet contain.
Signature = tuple[tuple[str, ...] | None, ...]

_DEFAULT_MAX_PAIRS = 2_000_000


def references_trm(node: ast.Expr) -> bool:
    """True iff evaluating ``node`` can observe the TRM binding.

    Raises on an unrecognized node type rather than defaulting to False, so
    that adding an AST node without updating this function fails loudly
    instead of silently declaring a rule TRM-blind.
    """
    match node:
        case ast.Trm():
            return True
        case ast.Inr() | ast.Symbol() | ast.FeatureSpec():
            return False
        case ast.FeatureNames() | ast.NcSequence():
            return False
        case ast.Slice(sequence=seq):
            return references_trm(seq)
        case ast.InClass(sequence=seq):
            return references_trm(seq)
        case ast.If(cond=cond, then=then, else_=else_):
            return (
                references_trm(cond)
                or references_trm(then)
                or references_trm(else_)
            )
        case ast.Unify(segment=seg, features=feats):
            return references_trm(seg) or references_trm(feats)
        case ast.Subtract(segment=seg):
            return references_trm(seg)
        case ast.Project(segment=seg):
            return references_trm(seg)
        case ast.Concat(args=args):
            return any(references_trm(arg) for arg in args)
        case _:
            raise CompileError(
                f"references_trm: unhandled AST node {node!r}. Add a case "
                "here when introducing a new node type."
            )


@dataclass(frozen=True)
class TrmQuotient:
    """The behaviour classes of a rule's licensed TRM-windows.

    Attributes:
        reps: One representative TRM-window per class, in word order. The
            index into this list is what a compiled state stores as ``p``.
        class_of: Maps a TRM-window (as a tuple of inventory names, in word
            order) to its class index. Windows absent from L(Trm) are absent
            here.
        produced: Every segment ``Out`` can emit over the licensed
            (INR-window, TRM-window) pairs — what alphabet propagation needs.
        trm_blind: True when neither Out nor Cnd can observe TRM, in which
            case every licensed window falls into a single class.
    """

    reps: list[lp.Word]
    class_of: dict[tuple[str, ...], int]
    produced: list[lp.Segment]
    trm_blind: bool


def _out_segments(
    rule: Rule,
    out_ast: ast.Expr,
    target: lp.Word,
    trigger: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
) -> list[lp.Segment]:
    raw = evaluate(out_ast, target, trigger, fs, inv)
    if isinstance(raw, bool):
        raise CompileError(
            f"Rule '{rule.Id}': Out expression evaluated to a boolean."
        )
    return list(raw)


def _names(word: lp.Word, inv: lp.Inventory) -> tuple[str, ...]:
    return tuple(inv.name_of(seg) for seg in word)


def trm_quotient(
    rule: Rule,
    out_ast: ast.Expr,
    cnd_ast: ast.Expr | None,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    *,
    max_pairs: int = _DEFAULT_MAX_PAIRS,
) -> TrmQuotient:
    """Partition the rule's licensed TRM-windows by observable behaviour.

    Also collects, at no extra cost, every segment ``Out`` can produce over
    the licensed pairs.

    Raises:
        CompileError: If the enumeration would exceed ``max_pairs``, or if Out
            evaluates to a boolean.
    """
    inr_ncs = rule.inr_as_ncs(fs)
    inr_words = list(inr_ncs.over(inv, filter_boundaries=False))

    if len(rule.Trm) == 0:
        # No terminator: a single vacuous class holding the empty window.
        empty = fs.word([])
        produced: list[lp.Segment] = []
        for target in inr_words:
            if eval_cnd(rule, cnd_ast, target, empty, fs, inv):
                produced.extend(
                    _out_segments(rule, out_ast, target, empty, fs, inv)
                )
        return TrmQuotient(
            reps=[empty], class_of={}, produced=produced, trm_blind=True
        )

    trm_words = list(rule.trm_as_ncs(fs).over(inv, filter_boundaries=False))

    if not trm_words:
        # Trm is satisfiable by no window at all, so the rule never fires.
        return TrmQuotient(
            reps=[], class_of={}, produced=[], trm_blind=False
        )

    blind = not references_trm(out_ast) and (
        cnd_ast is None or not references_trm(cnd_ast)
    )

    if blind:
        # Every licensed window behaves identically; one representative
        # suffices and the quadratic pass is unnecessary.
        rep = trm_words[0]
        produced = []
        for target in inr_words:
            if eval_cnd(rule, cnd_ast, target, rep, fs, inv):
                produced.extend(
                    _out_segments(rule, out_ast, target, rep, fs, inv)
                )
        return TrmQuotient(
            reps=[rep],
            class_of={_names(t, inv): 0 for t in trm_words},
            produced=produced,
            trm_blind=True,
        )

    pairs = len(inr_words) * len(trm_words)
    if pairs > max_pairs:
        raise CompileError(
            f"Rule '{rule.Id}': classifying this rule's terminators needs "
            f"{pairs:,} Out evaluations ({len(inr_words):,} Inr windows x "
            f"{len(trm_words):,} Trm windows), above the limit of "
            f"{max_pairs:,} — roughly {pairs * 1e-5:.0f} seconds of work. "
            "Narrow Inr or Trm so fewer segments match, or have Out and Cnd "
            "read TRM only through proj/in? so the rule is cheaper to "
            "classify."
        )

    reps: list[lp.Word] = []
    class_of: dict[tuple[str, ...], int] = {}
    seen: dict[Signature, int] = {}
    produced = []

    for trigger in trm_words:
        signature: list[tuple[str, ...] | None] = []
        emitted: list[lp.Segment] = []
        for target in inr_words:
            if not eval_cnd(rule, cnd_ast, target, trigger, fs, inv):
                signature.append(None)
                continue
            segs = _out_segments(rule, out_ast, target, trigger, fs, inv)
            signature.append(tuple(str(seg) for seg in segs))
            emitted.extend(segs)

        key: Signature = tuple(signature)
        index = seen.get(key)
        if index is None:
            index = len(reps)
            seen[key] = index
            reps.append(trigger)
            # Only a representative's output can be emitted at run time, but
            # every window in the class produces exactly the same segments by
            # construction, so collecting once per class is complete.
            produced.extend(emitted)
        class_of[_names(trigger, inv)] = index

    return TrmQuotient(
        reps=reps, class_of=class_of, produced=produced, trm_blind=False
    )
