"""FST compiler for S&C rules (pynini backend).

Supported cases:
  n=1, m=1  — trigger-conditioned rewrite (assimilation, vowel harmony, ...)
  n≥1, m=0  — unconditional rewrite (epenthesis, metathesis, ...)

For Dir=R, the same left-to-right FST is built and then reversed via
pynini.reverse(T), which correctly implements w → reverse(T(reverse(w))).
"""

from __future__ import annotations

from collections import deque
from itertools import product as iproduct

import pynini

from snc2fst import dsl, operations
from snc2fst.alphabet import BOS_SEGMENT, EOS_SEGMENT
from snc2fst.evaluator import evaluate
from snc2fst.models import Rule
from snc2fst.types import Segment

_BOUNDARY_NAMES = {"⋊": BOS_SEGMENT, "⋉": EOS_SEGMENT}


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
# Alphabet propagation
# ---------------------------------------------------------------------------

def _seg_key(seg: Segment) -> frozenset:
    return frozenset(seg.items())


def _auto_name(seg: Segment) -> str:
    """Canonical name for a segment not in the named alphabet."""
    parts = sorted(f"{v}{f}" for f, v in seg.items())
    return "[" + " ".join(parts) + "]"


def _expand_alphabet(
    base: dict[str, Segment],
    new_segs: list[Segment],
) -> dict[str, Segment]:
    """Return a copy of base extended with any segments in new_segs not already present."""
    result = dict(base)
    rev = {_seg_key(seg): name for name, seg in base.items()}
    for seg in new_segs:
        key = _seg_key(seg)
        if key not in rev:
            name = _auto_name(seg)
            result[name] = dict(seg)
            rev[key] = name
    return result


def _matching_combos(
    spec_seq: list,
    ext: dict[str, Segment],
    dir_r: bool,
) -> list[list[Segment]]:
    """Return all segment sequences from ext that model spec_seq.

    Instead of generating all |Σ|^n combinations and filtering, this builds
    the cross-product position-by-position: for each position i, only segments
    that match spec_seq[i] are considered.  For Dir=R rules the spec is applied
    in reverse order (rightmost position first) to match the reversed-input
    encoding used by the FST.

    For an empty spec (Trm=[[]]), the single empty spec matches any segment,
    so all segments are included at that position.
    """
    segs = list(ext.values())
    specs = list(reversed(spec_seq)) if dir_r else list(spec_seq)
    per_position = [
        [s for s in segs if operations.in_class(s, spec)]
        for spec in specs
    ]
    return [list(combo) for combo in iproduct(*per_position)]


def _rule_output_segs(
    rule: Rule,
    out_ast,
    alphabet: dict[str, Segment],
) -> list[Segment]:
    """Enumerate every segment Out can produce for the given rule and alphabet."""
    dir_r = rule.Dir == "R"
    m = len(rule.Trm)
    ext = _extended_alphabet(alphabet)
    produced: list[Segment] = []

    if m == 0:
        for combo in _matching_combos(rule.Inr, ext, dir_r):
            check = list(reversed(combo)) if dir_r else combo
            raw = evaluate(out_ast, check, [], alphabet)
            produced += [raw] if isinstance(raw, dict) else list(raw)
    else:  # n=1, m=1
        for inr_combo in _matching_combos(rule.Inr, ext, False):
            for trm_combo in _matching_combos(rule.Trm, ext, False):
                raw = evaluate(out_ast, inr_combo, trm_combo, alphabet)
                produced += [raw] if isinstance(raw, dict) else list(raw)

    return produced


def compute_alphabets(
    rules: list[Rule],
    base_alphabet: dict[str, Segment],
) -> list[dict[str, Segment]]:
    """Return the effective input alphabet for each rule.

    alphabets[i] is the alphabet rule i reads from — equal to base_alphabet
    for i=0, and the output alphabet of rule i-1 for i>0.  Any segment
    produced by Out that is not already named receives an auto-generated name
    based on its feature bundle (e.g. ``[-lab +nas -voc]``).
    """
    alphabets: list[dict[str, Segment]] = []
    current = base_alphabet
    for rule in rules:
        alphabets.append(current)
        out_ast = dsl.parse(rule.Out)
        new_segs = _rule_output_segs(rule, out_ast, current)
        current = _expand_alphabet(current, new_segs)
    return alphabets


# ---------------------------------------------------------------------------
# Arc count prediction
# ---------------------------------------------------------------------------

def predict_arcs(
    rule: Rule,
    alphabet: dict[str, Segment],
    out_ast,
) -> int:
    """Return the exact number of FST arcs the rule will produce before optimization.

    For n=1, m=1:
        base = |Σ| × (1 + |L(Trm)|)
        extra = Σ_{x ∈ L(Inr), σ ∈ L(Trm)} max(0, |Out(x,σ)| − 1)

    For n≥1, m=0:
        S    = 1 + |Σ| + ... + |Σ|^(n−1)   (total buffer states)
        base = (|Σ| + 1) × S − 1
        extra = Σ_{matching (buf+(x,))} max(0, |Out(buf_check)| − 1)
    """
    _check_compilable(rule)
    dir_r = rule.Dir == "R"
    n, m = len(rule.Inr), len(rule.Trm)
    ext = _extended_alphabet(alphabet)
    sigma = len(ext)
    seg_list = list(ext.values())

    if m == 1:  # n=1, m=1
        trm_segs = [s for s in seg_list if operations.models([s], rule.Trm)]
        inr_segs = [s for s in seg_list if operations.models([s], rule.Inr)]
        base = sigma * (1 + len(trm_segs))
        extra = 0
        for x_seg in inr_segs:
            for sigma_seg in trm_segs:
                raw = evaluate(out_ast, [x_seg], [sigma_seg], alphabet)
                k = 1 if isinstance(raw, dict) else len(list(raw))
                extra += max(0, k - 1)
        return base + extra

    else:  # m=0, n>=1
        s_total = sum(sigma ** k for k in range(n))
        base = (sigma + 1) * s_total - 1
        extra = 0
        for combo in _matching_combos(rule.Inr, ext, dir_r):
            check = list(reversed(combo)) if dir_r else combo
            raw = evaluate(out_ast, check, [], alphabet)
            k = 1 if isinstance(raw, dict) else len(list(raw))
            extra += max(0, k - 1)
        return base + extra


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extended_alphabet(alphabet: dict[str, Segment]) -> dict[str, Segment]:
    """Return alphabet extended with ⋊/⋉ boundary pseudo-segments."""
    ext = dict(alphabet)
    ext["⋊"] = dict(BOS_SEGMENT)
    ext["⋉"] = dict(EOS_SEGMENT)
    return ext


def _build_sym_table(alphabet: dict[str, Segment]) -> pynini.SymbolTable:
    sym = pynini.SymbolTable()
    sym.add_symbol("<eps>", 0)
    for name in _extended_alphabet(alphabet):
        sym.add_symbol(name)
    return sym


def _rev_map(alphabet: dict[str, Segment]) -> dict[frozenset, str]:
    """Reverse mapping from feature-set fingerprint to segment name."""
    rmap = {frozenset(seg.items()): name for name, seg in alphabet.items()}
    rmap[frozenset(BOS_SEGMENT.items())] = "⋊"
    rmap[frozenset(EOS_SEGMENT.items())] = "⋉"
    return rmap


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
    ext = _extended_alphabet(alphabet)
    sym = _build_sym_table(alphabet)
    rmap = _rev_map(alphabet)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    q_f = fst.add_state()
    fst.set_start(q_f)
    fst.set_final(q_f, w)

    # One state per segment in L(Trm), including boundary pseudo-segments
    trm_state: dict[str, int] = {}
    for name, seg in ext.items():
        if operations.models([seg], rule.Trm):
            s = fst.add_state()
            fst.set_final(s, w)
            trm_state[name] = s

    # Transitions from q_f: emit x unchanged, update state if x ∈ L(Trm)
    for x_name in ext:
        xl = sym.find(x_name)
        dst = trm_state.get(x_name, q_f)
        _emit_chain(fst, sym, q_f, xl, [x_name], dst, w)

    # Transitions from each q_σ
    for sigma_name, q_sigma in trm_state.items():
        sigma_seg = ext[sigma_name]
        for x_name, x_seg in ext.items():
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
    ext = _extended_alphabet(alphabet)
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

        for x_name, x_seg in ext.items():
            xl = sym.find(x_name)
            new_buf = buf + (x_name,)

            if len(new_buf) < n:
                # Buffer still filling — accumulate, emit nothing
                next_buf = new_buf
                _emit_chain(fst, sym, src, xl, [], get_state(next_buf), w)
            else:
                # Buffer full — check Inr match
                buf_segs = [ext[nm] for nm in new_buf]
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

def transduce(
    fst: "pynini.Fst",
    rule: Rule,
    segments: list[str],
) -> list[str]:
    """Apply a compiled FST to a list of segment names, returning output names.

    Handles Dir=R reversal internally — callers never need to reverse input
    or output themselves.  Raises ValueError if the FST produces no output
    for the given input (i.e. the input is not in the FST's domain).
    """
    sym = fst.input_symbols()
    output_sym = fst.output_symbols()
    one = pynini.Weight.one("tropical")

    inp = list(reversed(segments)) if rule.Dir == "R" else segments

    lin = pynini.Fst()
    s = lin.add_state()
    lin.set_start(s)
    for name in inp:
        t = lin.add_state()
        lin.add_arc(s, pynini.Arc(sym.find(name), sym.find(name), one, t))
        s = t
    lin.set_final(s, one)

    composed = pynini.compose(lin, fst)
    if composed.start() == -1:
        raise ValueError(f"FST produced no output for input {segments!r}")

    result = []
    state = composed.start()
    seen: set[int] = set()
    while state != -1 and state not in seen:
        seen.add(state)
        arcs = list(composed.arcs(state))
        if not arcs:
            break
        real = [a for a in arcs if a.ilabel != 0]
        arc = real[0] if real else arcs[0]
        if arc.olabel != 0:
            result.append(output_sym.find(arc.olabel))
        state = arc.nextstate

    if rule.Dir == "R":
        result = list(reversed(result))
    return result


def compile_rule(rule: Rule, alphabet: dict[str, Segment]) -> pynini.Fst:
    """Compile an S&C rule to a pynini FST transducer.

    The returned FST always reads left-to-right.  For Dir=R rules the FST
    encodes right-to-left semantics internally (reversed pattern checks,
    reversed output), so callers must feed the reversed input string and
    then reverse the output string to obtain the correct surface form.

    Pass the alphabet returned by ``compute_alphabets`` for this rule's
    position in the rule chain, not necessarily the base alphabet.
    """
    _check_compilable(rule)
    out_ast = dsl.parse(rule.Out)
    dir_r = rule.Dir == "R"
    if len(rule.Trm) == 0:
        return _compile_n_m0(rule, out_ast, alphabet, dir_r)
    return _compile_n1_m1(rule, out_ast, alphabet, dir_r)
