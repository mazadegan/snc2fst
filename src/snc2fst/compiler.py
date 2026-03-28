"""FST compiler for S&C rules (pynini backend).

Supported cases:
  n=1, m=1  — trigger-conditioned rewrite (assimilation, vowel harmony, ...)
  n≥1, m=0  — unconditional rewrite (epenthesis, metathesis, ...)

For Dir=R, the same left-to-right FST is built and then reversed via
pynini.reverse(T), which correctly implements w → reverse(T(reverse(w))).
"""

from __future__ import annotations

from collections import deque

import pynini

from snc2fst import dsl, operations
from snc2fst.evaluator import evaluate
from snc2fst.models import Rule
from snc2fst.types import Segment


class CompileError(Exception):
    pass


# ---------------------------------------------------------------------------
# Compilability check
# ---------------------------------------------------------------------------

def _check_compilable(rule: Rule) -> None:
    n, m = len(rule.Inr), len(rule.Trm)
    if n == 0:
        raise CompileError(
            f"Rule '{rule.Id}': Inr is empty (n=0); not supported."
        )
    if m == 0:
        return  # n>=1, m=0: supported
    if n == 1 and m == 1:
        return  # n=1, m=1: supported
    raise CompileError(
        f"Rule '{rule.Id}': (n={n}, m={m}) is not compilable. "
        "Only (n≥1, m=0) and (n=1, m=1) are supported."
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_sym_table(alphabet: dict[str, Segment]) -> pynini.SymbolTable:
    sym = pynini.SymbolTable()
    sym.add_symbol("<eps>", 0)
    for name in alphabet:
        sym.add_symbol(name)
    return sym


def _rev_map(alphabet: dict[str, Segment]) -> dict[frozenset, str]:
    """Reverse mapping from feature-set fingerprint to segment name."""
    return {frozenset(seg.items()): name for name, seg in alphabet.items()}


def _seg_name(seg: Segment, rmap: dict[frozenset, str]) -> str:
    key = frozenset(seg.items())
    if key not in rmap:
        raise CompileError(f"Out produced a segment not in the alphabet: {seg}")
    return rmap[key]


def _eval_out_names(
    inr_segs: list[Segment],
    trm_segs: list[Segment],
    out_ast,
    alphabet: dict[str, Segment],
    rmap: dict[frozenset, str],
) -> list[str]:
    result = evaluate(out_ast, inr_segs, trm_segs, alphabet)
    segs: list[Segment] = [result] if isinstance(result, dict) else list(result)
    return [_seg_name(s, rmap) for s in segs]


def _emit_chain(
    fst: pynini.Fst,
    sym: pynini.SymbolTable,
    src: int,
    ilabel: int,
    out_names: list[str],
    dst: int,
    w,
) -> None:
    """Add arcs from src consuming ilabel and emitting out_names, ending at dst.

    Multi-symbol output is encoded as one arc consuming the input followed by
    epsilon-input arcs for the remaining output symbols.
    """
    if not out_names:
        fst.add_arc(src, pynini.Arc(ilabel, 0, w, dst))
        return
    nodes = [src] + [fst.add_state() for _ in range(len(out_names) - 1)] + [dst]
    for i, name in enumerate(out_names):
        il = ilabel if i == 0 else 0
        fst.add_arc(nodes[i], pynini.Arc(il, sym.find(name), w, nodes[i + 1]))


# ---------------------------------------------------------------------------
# Case 1: n=1, m=1  (original S&C FST construction)
# ---------------------------------------------------------------------------

def _compile_n1_m1(
    rule: Rule,
    out_ast,
    alphabet: dict[str, Segment],
    dir_r: bool,
) -> pynini.Fst:
    sym = _build_sym_table(alphabet)
    rmap = _rev_map(alphabet)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    q_f = fst.add_state()
    fst.set_start(q_f)
    fst.set_final(q_f, w)

    # One state per segment in L(Trm)
    trm_state: dict[str, int] = {}
    for name, seg in alphabet.items():
        if operations.models([seg], rule.Trm):
            s = fst.add_state()
            fst.set_final(s, w)
            trm_state[name] = s

    # Transitions from q_f: emit x unchanged, update state if x ∈ L(Trm)
    for x_name in alphabet:
        xl = sym.find(x_name)
        dst = trm_state.get(x_name, q_f)
        _emit_chain(fst, sym, q_f, xl, [x_name], dst, w)

    # Transitions from each q_σ
    for sigma_name, q_sigma in trm_state.items():
        sigma_seg = alphabet[sigma_name]
        for x_name, x_seg in alphabet.items():
            xl = sym.find(x_name)
            if operations.models([x_seg], rule.Inr):
                out_names = _eval_out_names(
                    [x_seg], [sigma_seg], out_ast, alphabet, rmap
                )
            else:
                out_names = [x_name]
            # Next state: new trigger if x ∈ L(Trm), else stay at q_σ
            dst = trm_state.get(x_name, q_sigma)
            _emit_chain(fst, sym, q_sigma, xl, out_names, dst, w)

    fst.set_input_symbols(sym)
    fst.set_output_symbols(sym)
    return fst


# ---------------------------------------------------------------------------
# Case 2: n≥1, m=0  (sliding buffer)
# ---------------------------------------------------------------------------

def _compile_n_m0(
    rule: Rule,
    out_ast,
    alphabet: dict[str, Segment],
    dir_r: bool,
) -> pynini.Fst:
    n = len(rule.Inr)
    sym = _build_sym_table(alphabet)
    rmap = _rev_map(alphabet)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    state_map: dict[tuple[str, ...], int] = {}

    def get_state(buf: tuple[str, ...]) -> int:
        if buf not in state_map:
            state_map[buf] = fst.add_state()
        return state_map[buf]

    fst.set_start(get_state(()))

    queue: deque[tuple[str, ...]] = deque([()])
    visited: set[tuple[str, ...]] = {()}

    while queue:
        buf = queue.popleft()
        src = get_state(buf)

        for x_name, x_seg in alphabet.items():
            xl = sym.find(x_name)
            new_buf = buf + (x_name,)

            if len(new_buf) < n:
                # Buffer still filling — accumulate, emit nothing
                next_buf = new_buf
                _emit_chain(fst, sym, src, xl, [], get_state(next_buf), w)
            else:
                # Buffer full — check Inr match
                buf_segs = [alphabet[nm] for nm in new_buf]
                # For Dir=R, input arrives in reversed order; check reversed buf
                check_segs = list(reversed(buf_segs)) if dir_r else buf_segs

                if operations.models(check_segs, rule.Inr):
                    out_names = _eval_out_names(
                        check_segs, [], out_ast, alphabet, rmap
                    )
                    # Reverse output so pynini.reverse restores original order
                    if dir_r:
                        out_names = list(reversed(out_names))
                    next_buf = ()
                else:
                    # No match — emit oldest segment, slide buffer
                    out_names = [new_buf[0]]
                    next_buf = new_buf[1:]

                _emit_chain(fst, sym, src, xl, out_names, get_state(next_buf), w)

            if next_buf not in visited:
                visited.add(next_buf)
                queue.append(next_buf)

    # Final states: flush remaining buffer via epsilon arcs.
    # Each buffer state (s1, ..., sk) emits s1 and transitions to (s2, ..., sk).
    # The empty buffer is the only accepting state; all paths lead there.
    #
    # Flush arcs get a higher weight than regular arcs so that shortestpath
    # prefers real transitions over premature flushing when both are available.
    w_flush = pynini.Weight("tropical", "1")
    for buf, buf_state in list(state_map.items()):
        if not buf:
            fst.set_final(buf_state, w)
        else:
            fst.add_arc(
                buf_state,
                pynini.Arc(0, sym.find(buf[0]), w_flush, get_state(buf[1:])),
            )

    fst.set_input_symbols(sym)
    fst.set_output_symbols(sym)
    return fst


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_rule(rule: Rule, alphabet: dict[str, Segment]) -> pynini.Fst:
    """Compile an S&C rule to a pynini FST transducer.

    The returned FST always reads left-to-right.  For Dir=R rules the FST
    encodes right-to-left semantics internally (reversed pattern checks,
    reversed output), so callers must feed the reversed input string and
    then reverse the output string to obtain the correct surface form.
    """
    _check_compilable(rule)
    out_ast = dsl.parse(rule.Out)
    dir_r = rule.Dir == "R"
    if len(rule.Trm) == 0:
        return _compile_n_m0(rule, out_ast, alphabet, dir_r)
    return _compile_n1_m1(rule, out_ast, alphabet, dir_r)
