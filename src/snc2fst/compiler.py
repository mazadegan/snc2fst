"""FST compiler for S&C rules (pynini backend).

Supported cases:
  n=1, m=1  — trigger-conditioned rewrite (assimilation, vowel harmony, ...)
  n≥1, m=0  — unconditional rewrite (epenthesis, metathesis, ...)

For Dir=R, the same left-to-right FST is built and then used with reversed
input/output, which correctly implements w → reverse(T(reverse(w))).

Alphabet propagation
--------------------
Each rule reads from an ``lp.Inventory``.  The first rule uses the inventory
loaded from ``alphabet.csv``.  After each rule its output alphabet is computed
by evaluating ``Out`` on every valid (INR, TRM) pair; any segment not yet in
the inventory is added under its canonical name (e.g. ``{+nas-voc}``).  A
warning is emitted for every such novel segment so that users know what will
appear in rendered output.
"""

from __future__ import annotations

import warnings
from collections import deque

import logical_phonology as lp

# pynini has incomplete type stubs; type errors from
# pynini calls are suppressed throughout this file.
import pynini  # type: ignore[import]

from snc2fst import dsl
from snc2fst import dsl_ast as ast
from snc2fst.errors import CompileError
from snc2fst.evaluator import evaluate
from snc2fst.models import Rule

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
        return  # n≥1, m=0: supported
    if n == 1 and m == 1:
        return  # n=1, m=1: supported
    raise CompileError(
        f"Rule '{rule.Id}': (n={n}, m={m}) is not compilable. "
        "Only (n≥1, m=0) and (n=1, m=1) are supported."
    )


# ---------------------------------------------------------------------------
# Inventory / alphabet helpers
# ---------------------------------------------------------------------------


def _all_segments(inv: lp.Inventory) -> list[lp.Segment]:
    """Return all segments in the inventory, including BOS/EOS boundaries."""
    return list(inv.segment_to_name.keys())


def _rule_output_segments(
    rule: Rule,
    out_ast: ast.Expr,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
) -> list[lp.Segment]:
    """Enumerate every distinct segment that Out can produce for this rule.

    For n=1, m=1: evaluates Out over all (inr_seg, trm_seg) pairs where
    inr_seg ∈ L(Inr) and trm_seg ∈ L(Trm).

    For n≥1, m=0: evaluates Out over all inr_word ∈ L(Inr) (no trigger).

    BOS/EOS are included in the enumeration because rules may legitimately
    condition on boundaries, but boundary pseudo-segments are never added to
    the output inventory (they are always present in every inventory already).
    """
    inr_ncs = rule.inr_as_ncs(fs)
    produced: list[lp.Segment] = []

    if len(rule.Trm) == 0:
        # n≥1, m=0 — iterate over all words in L(Inr)
        # filter_boundaries=False so boundary-conditioned rules work
        for inr_word in inr_ncs.over(inv, filter_boundaries=False):
            if rule.Dir == "R":
                inr_word = fs.word(list(reversed(list(inr_word))))
            raw = evaluate(out_ast, inr_word, fs.word([]), fs, inv)
            if isinstance(raw, lp.Word):
                produced.extend(list(raw))  # type: ignore[arg-type]
            # bool case (shouldn't happen during alphabet propagation) is silently ignored # noqa: E501
    else:
        # n=1, m=1 — iterate over all (inr, trm) pairs
        trm_ncs = rule.trm_as_ncs(fs)
        for inr_word in inr_ncs.over(inv, filter_boundaries=False):
            for trm_word in trm_ncs.over(inv, filter_boundaries=False):
                raw = evaluate(out_ast, inr_word, trm_word, fs, inv)
                if isinstance(raw, lp.Word):
                    produced.extend(list(raw))  # type: ignore[arg-type]
                # bool case (shouldn't happen during alphabet propagation) is silently ignored # noqa: E501

    return produced


def _extend_inventory(
    inv: lp.Inventory,
    new_segments: list[lp.Segment],
    rule_id: str,
) -> lp.Inventory:
    """Return a new inventory extended with any segments not already present.

    Novel segments are named by their canonical form (e.g. ``{+nas-voc}``).
    A warning is emitted for each novel segment.
    """
    to_add: dict[str, lp.Segment] = {}
    for seg in new_segments:
        # Skip BOS/EOS — they are always present
        if seg == inv.feature_system.BOS or seg == inv.feature_system.EOS:
            continue
        if seg not in inv:
            canonical = str(seg)
            if canonical not in to_add:
                to_add[canonical] = seg
                warnings.warn(
                    f"Rule '{rule_id}': Out expression produced segment "
                    f"{canonical!r} which is not in the current alphabet. "
                    f"It will appear as its canonical form {canonical!r} in "
                    "rendered output. Consider adding it to alphabet.csv.",
                    stacklevel=3,
                )
    if not to_add:
        return inv
    return inv.extend(to_add)


def compute_alphabets(
    rules: list[Rule],
    fs: lp.FeatureSystem,
    base_inv: lp.Inventory,
) -> list[lp.Inventory]:
    """Return the effective input inventory for each rule.

    ``alphabets[i]`` is the inventory rule ``i`` reads from — equal to
    ``base_inv`` for ``i=0``, and the output inventory of rule ``i-1`` for
    ``i>0``.
    """
    alphabets: list[lp.Inventory] = []
    current = base_inv
    for rule in rules:
        alphabets.append(current)
        out_ast = dsl.parse(rule.Out)
        new_segs = _rule_output_segments(rule, out_ast, fs, current)
        current = _extend_inventory(current, new_segs, rule.Id)
    return alphabets


# ---------------------------------------------------------------------------
# Arc-count guard
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ARCS = 1_000_000


# ---------------------------------------------------------------------------
# Symbol table helpers
# ---------------------------------------------------------------------------


def _build_sym_table(inv: lp.Inventory) -> pynini.SymbolTable:
    """Build a pynini SymbolTable from an inventory.

    Epsilon is assigned label 0. All segment names (including ⋉/⋊) get
    sequential positive integer labels.
    """
    sym = pynini.SymbolTable()
    sym.add_symbol("<eps>", 0)
    for name in inv.name_to_segment:
        sym.add_symbol(name)
    return sym


# ---------------------------------------------------------------------------
# Arc emission helper
# ---------------------------------------------------------------------------


def _emit_chain(
    fst: pynini.Fst,
    sym: pynini.SymbolTable,
    src: int,
    ilabel: int,
    out_names: list[str],
    dst: int,
    w: pynini.Weight,
    rule_id: str,
    max_arcs: int,
    arc_count: list[int],
) -> None:
    """Add arcs from src consuming ilabel and emitting out_names, ending at dst.

    Multi-symbol output is encoded as one arc consuming the input label
    followed by epsilon-input arcs for the remaining output symbols.
    Checks arc limit after each arc addition.
    """  # noqa: E501

    def _add(s: int, arc: pynini.Arc) -> None:
        fst.add_arc(s, arc)
        arc_count[0] += 1
        if arc_count[0] > max_arcs:
            raise CompileError(
                f"Rule '{rule_id}': FST exceeded arc limit "
                f"({arc_count[0]} > {max_arcs}). "
                "Pass a higher --max-arcs value if this rule is intentionally large."  # noqa: E501
            )

    if not out_names:
        _add(src, pynini.Arc(ilabel, 0, w, dst))
        return

    nodes = (
        [src] + [fst.add_state() for _ in range(len(out_names) - 1)] + [dst]
    )
    for i, name in enumerate(out_names):
        il = ilabel if i == 0 else 0
        _add(nodes[i], pynini.Arc(il, sym.find(name), w, nodes[i + 1]))


# ---------------------------------------------------------------------------
# Output name resolution
# ---------------------------------------------------------------------------


def _out_names_for(
    out_ast,
    inr_word: lp.Word,
    trm_word: lp.Word,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    rule_id: str,
) -> list[str]:
    """Evaluate Out and return a list of segment names for the output."""
    raw = evaluate(out_ast, inr_word, trm_word, fs, inv)
    if isinstance(raw, bool):
        raise CompileError(
            f"Rule '{rule_id}': Out expression evaluated to a boolean."
        )
    segs: list[lp.Segment] = list(raw) if isinstance(raw, lp.Word) else [raw]
    names: list[str] = []
    for seg in segs:
        if seg not in inv:
            raise CompileError(
                f"Rule '{rule_id}': Out produced segment {seg!r} not in "
                "inventory. This should not happen — check compute_alphabets."
            )
        names.append(inv.name_of(seg))
    return names


# ---------------------------------------------------------------------------
# Case 1: n=1, m=1  (trigger-conditioned rewrite)
# ---------------------------------------------------------------------------


def _compile_n1_m1(
    rule: Rule,
    out_ast,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    max_arcs: int,
) -> pynini.Fst:
    """Build the S&C FST for the n=1, m=1 case.

    States:
      q_f  — the "free" state (no pending trigger seen)
      q_σ  — one state per segment σ ∈ L(Trm), representing "last seen σ"

    Transitions from q_f:
      For each x in Σ: emit x unchanged; move to q_x if x ∈ L(Trm), else q_f.

    Transitions from q_σ:
      For each x in Σ:
        If x ∈ L(Inr): emit Out(x, σ); move to q_x or q_σ.
        Else:           emit x unchanged; move to q_x or q_σ.
    """
    arc_count: list[int] = [0]

    sym = _build_sym_table(inv)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    inr_ncs = rule.inr_as_ncs(fs)
    trm_ncs = rule.trm_as_ncs(fs)
    all_segs = _all_segments(inv)

    q_f = fst.add_state()
    fst.set_start(q_f)
    fst.set_final(q_f, w)

    # One state per segment in L(Trm)
    trm_states: dict[lp.Segment, int] = {}
    for seg in all_segs:
        word = fs.word([seg])
        if word in trm_ncs:
            s = fst.add_state()
            fst.set_final(s, w)
            trm_states[seg] = s

    # Transitions from q_f
    for x_seg in all_segs:
        xl = sym.find(inv.name_of(x_seg))
        dst: int = trm_states[x_seg] if x_seg in trm_states else q_f
        _emit_chain(
            fst,
            sym,
            q_f,
            xl,
            [inv.name_of(x_seg)],
            dst,
            w,
            rule.Id,
            max_arcs,
            arc_count,
        )

    # Transitions from each trigger state q_σ
    for sigma_seg, q_sigma in trm_states.items():
        sigma_word = fs.word([sigma_seg])
        for x_seg in all_segs:
            xl = sym.find(inv.name_of(x_seg))
            x_word = fs.word([x_seg])
            if x_word in inr_ncs:
                out_names = _out_names_for(
                    out_ast, x_word, sigma_word, fs, inv, rule.Id
                )
            else:
                out_names = [inv.name_of(x_seg)]
            # Next state: new trigger if x ∈ L(Trm), else stay at q_σ
            dst: int = trm_states[x_seg] if x_seg in trm_states else q_sigma
            _emit_chain(
                fst,
                sym,
                q_sigma,
                xl,
                out_names,
                dst,
                w,
                rule.Id,
                max_arcs,
                arc_count,
            )

    fst.set_input_symbols(sym)
    fst.set_output_symbols(sym)
    return fst


# ---------------------------------------------------------------------------
# Case 2: n≥1, m=0  (sliding buffer)
# ---------------------------------------------------------------------------


def _compile_n_m0(
    rule: Rule,
    out_ast,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    max_arcs: int,
) -> pynini.Fst:
    """Build the S&C FST for the n≥1, m=0 case using a sliding buffer.

    Each state represents a tuple of segment names accumulated since the last
    match or flush.  When the buffer reaches length n:
      - If it models Inr: emit Out(...), reset buffer to ().
      - Else: emit the oldest buffered segment, slide the buffer by one.

    For Dir=R, input arrives reversed so the pattern check is also reversed.
    Output is likewise reversed so that pynini.reverse restores order.

    Boundary handling
    -----------------
    ``transduce`` always wraps every input with BOS (⋉) on the left and EOS
    (⋊) on the right before feeding this FST.  The terminal boundary symbol
    (EOS for Dir=L, BOS for Dir=R) is handled with a dedicated arc from every
    non-empty buffer state: it either fires the rule (if the buffer + terminal
    matches Inr) or flushes the entire buffer plus the terminal in one shot.
    This means the terminal symbol is *consumed* as a real input label rather
    than via an epsilon arc, which eliminates the mid-string nondeterminism
    that would otherwise arise from epsilon-input flush arcs.
    """
    arc_count: list[int] = [0]

    n = len(rule.Inr)
    dir_r = rule.Dir == "R"
    sym = _build_sym_table(inv)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    inr_ncs = rule.inr_as_ncs(fs)
    all_segs = _all_segments(inv)

    # Terminal boundary symbol: EOS for left-to-right, BOS for right-to-left.
    terminal_seg = fs.BOS if dir_r else fs.EOS
    terminal_name = inv.name_of(terminal_seg)

    state_map: dict[tuple[str, ...], int] = {}

    def get_state(buf: tuple[str, ...]) -> int:
        if buf not in state_map:
            state_map[buf] = fst.add_state()
        return state_map[buf]

    start = get_state(())
    fst.set_start(start)

    queue: deque[tuple[str, ...]] = deque([()])
    visited: set[tuple[str, ...]] = {()}

    while queue:
        buf = queue.popleft()
        src = get_state(buf)

        for x_seg in all_segs:
            x_name = inv.name_of(x_seg)
            xl = sym.find(x_name)
            new_buf = buf + (x_name,)

            if x_seg == terminal_seg:
                # Terminal boundary: either match or flush everything.
                # This arc consumes the real terminal label so it cannot be
                # taken mid-string, preventing nondeterministic early flushing.
                if len(new_buf) == n:
                    buf_segs = [inv[nm] for nm in new_buf]
                    check_segs = (
                        list(reversed(buf_segs)) if dir_r else buf_segs
                    )
                    check_word = fs.word(check_segs)
                    if check_word in inr_ncs:
                        out_names = _out_names_for(
                            out_ast, check_word, fs.word([]), fs, inv, rule.Id
                        )
                        if dir_r:
                            out_names = list(reversed(out_names))
                        next_buf = ()
                        _emit_chain(
                            fst,
                            sym,
                            src,
                            xl,
                            out_names,
                            get_state(next_buf),
                            w,
                            rule.Id,
                            max_arcs,
                            arc_count,
                        )
                        if next_buf not in visited:
                            visited.add(next_buf)
                            queue.append(next_buf)
                        continue
                # No match (or buffer too short): flush all buffered + terminal.
                flush_names = list(buf) + [x_name]
                next_buf = ()
                _emit_chain(
                    fst,
                    sym,
                    src,
                    xl,
                    flush_names,
                    get_state(next_buf),
                    w,
                    rule.Id,
                    max_arcs,
                    arc_count,
                )
                if next_buf not in visited:
                    visited.add(next_buf)
                    queue.append(next_buf)
                continue

            if len(new_buf) < n:
                # Buffer still filling — accumulate, emit nothing yet
                next_buf = new_buf
                _emit_chain(
                    fst,
                    sym,
                    src,
                    xl,
                    [],
                    get_state(next_buf),
                    w,
                    rule.Id,
                    max_arcs,
                    arc_count,
                )
            else:
                # Buffer full — check whether it models Inr
                buf_segs = [inv[nm] for nm in new_buf]
                # For Dir=R, input arrives reversed; check reversed buffer
                check_segs = list(reversed(buf_segs)) if dir_r else buf_segs
                check_word = fs.word(check_segs)

                if check_word in inr_ncs:
                    out_names = _out_names_for(
                        out_ast, check_word, fs.word([]), fs, inv, rule.Id
                    )
                    if dir_r:
                        out_names = list(reversed(out_names))
                    next_buf = ()
                else:
                    # No match — emit oldest segment, slide buffer
                    out_names = [new_buf[0]]
                    next_buf = new_buf[1:]

                _emit_chain(
                    fst,
                    sym,
                    src,
                    xl,
                    out_names,
                    get_state(next_buf),
                    w,
                    rule.Id,
                    max_arcs,
                    arc_count,
                )

            if next_buf not in visited:
                visited.add(next_buf)
                queue.append(next_buf)

    # The empty buffer is the only accepting state.
    # Non-empty buffer states are non-accepting: every valid path must consume
    # the terminal boundary symbol (added by transduce) and reach () that way.
    for buf, buf_state in state_map.items():
        if not buf:
            fst.set_final(buf_state, w)

    fst.set_input_symbols(sym)
    fst.set_output_symbols(sym)
    return fst


# ---------------------------------------------------------------------------
# BOS / EOS symbol names (used for boundary wrapping in transduce)
# ---------------------------------------------------------------------------

_BOS_NAME = "⋉"
_EOS_NAME = "⋊"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_rule(
    rule: Rule,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    max_arcs: int = _DEFAULT_MAX_ARCS,
) -> pynini.Fst:
    """Compile an S&C rule to a pynini FST transducer.

    For Dir=R rules the FST encodes right-to-left semantics internally:
    the caller must feed the reversed input string and then reverse the output
    string to obtain the correct surface form.  ``transduce`` handles this
    automatically.

    Args:
        rule:     The Rule to compile.
        fs:       The FeatureSystem for this rule's position in the chain.
        inv:      The inventory for this rule's position in the chain
                  (i.e. the output of ``compute_alphabets``).
        max_arcs: Soft arc-count limit; raises CompileError if exceeded during
                  construction. Defaults to 1,000,000.

    Returns:
        A compiled pynini.Fst transducer.

    Raises:
        CompileError: If the rule is not compilable or exceeds max_arcs.
    """
    _check_compilable(rule)
    out_ast = dsl.parse(rule.Out)
    if len(rule.Trm) == 0:
        return _compile_n_m0(rule, out_ast, fs, inv, max_arcs)
    return _compile_n1_m1(rule, out_ast, fs, inv, max_arcs)


def transduce(
    fst: pynini.Fst,
    rule: Rule,
    segment_names: list[str],
) -> list[str]:
    sym = fst.input_symbols()
    out_sym = fst.output_symbols()
    one = pynini.Weight.one("tropical")

    # Wrap with BOS/EOS so the FST can match boundary-sensitive rules and so
    # that the terminal-flush arcs (which replace epsilon flush arcs) fire at
    # the correct position.  BOS and EOS are stripped from the output afterward.
    has_bos = sym.find(_BOS_NAME) != -1
    has_eos = sym.find(_EOS_NAME) != -1
    if has_bos and has_eos:
        wrapped = [_BOS_NAME] + list(segment_names) + [_EOS_NAME]
    else:
        wrapped = list(segment_names)

    inp = list(reversed(wrapped)) if rule.Dir == "R" else wrapped

    # Build a linear acceptor for the input
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
        raise ValueError(
            f"Rule '{rule.Id}': FST produced no output for input "
            f'"{" ".join(inp)}"'
        )

    # Use pynini's shortest path + string extraction instead of manual walk.
    # The manual walk incorrectly skips epsilon-input arcs produced by
    # multi-symbol output chains (_emit_chain), dropping inserted segments.
    shortest = pynini.shortestpath(composed)
    shortest.rmepsilon()

    result: list[str] = []
    state = shortest.start()
    seen: set[int] = set()
    while state != -1 and state not in seen:
        seen.add(state)
        arcs = list(shortest.arcs(state))
        if not arcs:
            break
        arc = arcs[0]
        if arc.olabel != 0:
            result.append(out_sym.find(arc.olabel))
        state = arc.nextstate

    if rule.Dir == "R":
        result = list(reversed(result))

    # Strip the boundary markers added above.
    if has_bos and result and result[0] == _BOS_NAME:
        result = result[1:]
    if has_eos and result and result[-1] == _EOS_NAME:
        result = result[:-1]

    return result
