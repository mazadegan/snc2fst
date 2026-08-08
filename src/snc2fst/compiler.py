"""FST compiler for S&C rules (pynini backend).

Every well-formed rule compiles, for any ``m = len(Inr) >= 1`` and
``n = len(Trm) >= 0``.  A single construction (``_compile_general``) covers
all of them; the former shape-specific builders were exactly its degenerate
cases.  It is ``evaluator.apply_rule`` tabulated — that evaluator is the
reference implementation, so a disagreement between the two is a bug here.

For Dir=R, the same left-to-right FST is built and then used with reversed
input/output, which correctly implements w → reverse(T(reverse(w))).

Machine size
------------
A configuration is ``(B, T, p)``: the INR-window buffer, the TRM-window
buffer, and the nearest licensed TRM-match.  Stored literally, ``p`` would
range over all of ``L(Trm)`` and the configuration count would grow as
``|Sigma|^(m + 2n - 2)`` — infeasible past n=1 on a realistic inventory
(a 24-segment alphabet at m=3, n=2 needs ~1M arcs).

Instead ``p`` is stored as a *behaviour class*: two TRM-windows share a state
when no ``Out`` or ``Cnd`` can tell them apart (see ``snc2fst.quotient``).
A rule reading TRM only through ``proj`` sees just the projected features, and
a rule ignoring TRM entirely collapses to one class.  That buys back roughly a
full unit of ``n`` — the 24-segment m=3, n=2 case drops to ~60k arcs.  The
denoted relation is unchanged; only the state count is.

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
from snc2fst.evaluator import eval_cnd, evaluate
from snc2fst.models import Rule
from snc2fst.quotient import TrmQuotient, trm_quotient
from snc2fst.wellformed import check_wellformed

# ---------------------------------------------------------------------------
# Compilability check
# ---------------------------------------------------------------------------


def _estimate_arcs(sigma: int, m: int, n: int, classes: int) -> int:
    """Upper bound on the arcs the construction will emit.

    A configuration is ``(B, T, p)``. ``B`` holds fewer than ``m`` segments
    between steps and ``T`` fewer than ``n``, but both are suffixes of the
    same scan history, so ``T`` is determined by ``B`` once ``|B| >= n-1``;
    the reachable count is therefore
    ``(classes + 1) * sum_k |Sigma|^max(k, n-1)`` rather than the product of
    the two. One arc leaves each configuration per input symbol.

    Approximate in both directions: pessimistic because not every pointer
    class is jointly reachable with every buffer pair, optimistic because it
    treats the TRM buffer as always full and ignores the extra arcs a
    multi-symbol output chain adds. Measured against real builds it lands
    within a few percent — close enough to make the rejection message useful,
    which is all it is for. The in-loop guard in ``_emit_chain`` remains the
    authoritative limit.
    """
    return sigma * (classes + 1) * sum(
        sigma ** max(k, n - 1) for k in range(m)
    )


def _check_size(
    rule: Rule, sigma: int, classes: int, max_arcs: int
) -> None:
    """Reject a rule whose machine would blow past the arc limit.

    Checked up front so the failure names the shape and a workable limit,
    rather than surfacing partway through construction as a bare count.
    """
    m, n = len(rule.Inr), len(rule.Trm)
    estimate = _estimate_arcs(sigma, m, n, classes)
    if estimate <= max_arcs:
        return
    raise CompileError(
        f"Rule '{rule.Id}': this rule needs roughly {estimate:,} arcs, "
        f"above the limit of {max_arcs:,}. It has m={m}, n={n} over an "
        f"alphabet of {sigma} symbols, and its Trm windows fall into "
        f"{classes} distinct behaviour class(es); size grows roughly as "
        f"|alphabet|^(m+n-1) x (classes+1), so n costs more than m. Either "
        f"pass --max-arcs {estimate:,} (or higher), or narrow Inr/Trm so "
        "fewer segments match."
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
    cnd_ast: ast.Expr | None = None,
) -> list[lp.Segment]:
    """Enumerate every segment that Out can produce for this rule.

    Delegates to the terminator quotient, which walks exactly the licensed
    (INR-window, TRM-window) pairs and collects their outputs along the way.
    Pairs the rule's Cnd rejects are skipped, since Out is never evaluated on
    them at run time and segments reachable only that way must not enter the
    alphabet.

    BOS/EOS are included in the enumeration because rules may legitimately
    condition on boundaries, but boundary pseudo-segments are never added to
    the output inventory (they are always present in every inventory already).
    """
    return trm_quotient(rule, out_ast, cnd_ast, fs, inv).produced


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
    """Return the effective inventory for each rule's transducer.

    ``alphabets[i]`` is everything rule ``i``'s FST must be able to name: the
    segments it can read (its input inventory, i.e. ``base_inv`` extended by
    every earlier rule's output) *together with* the segments its own ``Out``
    can produce.

    Both halves are needed. Omitting the rule's own outputs — as this did
    previously, by recording the inventory before extending it — left
    ``_out_names_for`` unable to name a segment the rule itself synthesizes,
    so any rule producing a novel segment failed to compile.

    ``Out`` is still evaluated against the *input* inventory, so ``&name``
    lookups resolve exactly where they did before.
    """
    alphabets: list[lp.Inventory] = []
    current = base_inv
    for rule in rules:
        out_ast = dsl.parse(rule.Out)
        cnd_ast = dsl.parse(rule.Cnd) if rule.Cnd is not None else None
        new_segs = _rule_output_segments(
            rule, out_ast, fs, current, cnd_ast
        )
        current = _extend_inventory(current, new_segs, rule.Id)
        alphabets.append(current)
    return alphabets


# ---------------------------------------------------------------------------
# Arc-count guard
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ARCS = 1_000_000
_SEQ_MAP_PREFIX = "__SEQMAP__:"
_SEQ_META_SEP = "|"
_SEQ_META_EQ = "="
_SEQ_META_ESC = "\\"


# ---------------------------------------------------------------------------
# Symbol table helpers
# ---------------------------------------------------------------------------


def _build_sym_table(inv: lp.Inventory) -> pynini.SymbolTable:
    """Build a pynini SymbolTable from an inventory.

    Epsilon is assigned label 0. All segment names (including ⋉/⋊) get
    sequential positive integer labels.
    """
    sym = pynini.SymbolTable()
    sym.set_name("snc2fst_symbols")
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
    collapse_multisymbol_output: bool = False,
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

    if collapse_multisymbol_output and len(out_names) > 1:
        seq_sym = _encode_sequence_symbol(out_names)
        _register_sequence_mapping(sym, seq_sym, out_names)
        olabel = sym.find(seq_sym)
        if olabel == -1:
            olabel = sym.add_symbol(seq_sym)
        _add(src, pynini.Arc(ilabel, olabel, w, dst))
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
# BOS / EOS symbol names (used for boundary wrapping in transduce)
# ---------------------------------------------------------------------------

_BOS_NAME = "⋉"
_EOS_NAME = "⋊"


# ---------------------------------------------------------------------------
# The compiled machine
# ---------------------------------------------------------------------------


def _compile_general(
    rule: Rule,
    out_ast,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    max_arcs: int,
    collapse_multisymbol_output: bool = False,
    cnd_ast=None,
    quotient: TrmQuotient | None = None,
) -> pynini.Fst:
    """Build the S&C FST for any well-formed rule (m≥1, n≥0).

    This is ``evaluator.apply_rule`` tabulated. A configuration is

        (B, T, p)

    where ``B`` holds up to ``m`` scanned segments (the candidate INR-window),
    ``T`` up to ``n-1`` (the candidate TRM-window), and ``p`` identifies the
    nearest licensed TRM-match, or is None when none has been seen. Per input
    symbol the machine pushes onto ``B``; resolves ``B`` if it is full, either
    firing (emitting Out and clearing ``B``) or sliding by one; and only then
    latches ``T``/``p``. That order is load-bearing — latching first would let
    a position license itself.

    ``p`` is stored as an index into ``quotient.reps``, a behaviour class
    rather than a literal window (see ``snc2fst.quotient``). Two TRM-windows
    the rule cannot distinguish share a state, which is what keeps the machine
    buildable: with literal windows the configuration count grows as
    ``|Sigma|^(m + 2n - 2)`` and exceeds the arc limit at n=2 on a 24-segment
    inventory.

    Buffers are held in *read* order, which is word order for Dir=L but
    reversed for Dir=R, since ``transduce`` feeds the machine a reversed
    string. Both buffers are therefore flipped back to word order before being
    matched, ``p`` is stored in word order so ``TRM[1]`` means what the DSL
    says, and each Out chunk is flipped to tape order before emission.

    Boundary handling: the terminal boundary symbol
    is consumed as a real input label rather than via an epsilon arc, so the
    residual flush cannot fire mid-string and make the machine
    nondeterministic.
    """
    arc_count: list[int] = [0]

    m, n = len(rule.Inr), len(rule.Trm)
    dir_r = rule.Dir == "R"
    sym = _build_sym_table(inv)
    w = pynini.Weight.one("tropical")
    fst = pynini.Fst()

    inr_ncs = rule.inr_as_ncs(fs)
    trm_ncs = rule.trm_as_ncs(fs)
    all_segs = _all_segments(inv)
    names = {seg: inv.name_of(seg) for seg in all_segs}
    labels = {name: sym.find(name) for name in names.values()}

    terminal_name = names[fs.BOS if dir_r else fs.EOS]

    q = quotient or trm_quotient(rule, out_ast, cnd_ast, fs, inv)

    def to_word(buf: tuple[str, ...]) -> lp.Word:
        """Read-order buffer -> word-order Word."""
        segs = [inv[name] for name in buf]
        return fs.word(list(reversed(segs)) if dir_r else segs)

    fire_memo: dict[tuple[tuple[str, ...], int | None], list[str] | None] = {}

    def fire(buf: tuple[str, ...], p: int | None) -> list[str] | None:
        """Tape-order output if this window fires, else None.

        Note the distinction between None (did not fire) and [] (fired with
        an empty output, i.e. a deletion rule) — callers must test ``is not
        None``.
        """
        key = (buf, p)
        if key in fire_memo:
            return fire_memo[key]
        result: list[str] | None = None
        if p is not None:
            target = to_word(buf)
            trigger = q.reps[p]
            if target in inr_ncs and eval_cnd(
                rule, cnd_ast, target, trigger, fs, inv
            ):
                result = _out_names_for(
                    out_ast, target, trigger, fs, inv, rule.Id
                )
                if dir_r:
                    result = list(reversed(result))
        fire_memo[key] = result
        return result

    def latch(
        tbuf: tuple[str, ...], p: int | None, name: str
    ) -> tuple[tuple[str, ...], int | None]:
        """Fold a scanned segment into the TRM buffer and pointer."""
        if n == 0:
            return tbuf, p  # no terminator to track
        candidate = tbuf + (name,)
        if len(candidate) < n:
            return candidate, p
        window = to_word(candidate)
        if window in trm_ncs:
            key = tuple(inv.name_of(seg) for seg in window)
            # A window can match Trm yet be absent from class_of only if the
            # quotient found no licensed windows at all, in which case the
            # rule never fires and leaving p alone is correct.
            p = q.class_of.get(key, p)
        return candidate[1:], p

    State = tuple[tuple[str, ...], tuple[str, ...], int | None]
    state_map: dict[State, int] = {}

    def get_state(key: State) -> int:
        if key not in state_map:
            state_map[key] = fst.add_state()
        return state_map[key]

    # With no terminator every position is trivially licensed, which the
    # quotient represents as the single class holding the empty window.
    start: State = ((), (), 0 if n == 0 else None)
    fst.set_start(get_state(start))

    queue: deque[State] = deque([start])
    visited: set[State] = {start}

    while queue:
        buf, tbuf, p = queue.popleft()
        src = get_state((buf, tbuf, p))

        for x_seg in all_segs:
            x_name = names[x_seg]
            new_buf = buf + (x_name,)

            if x_name == terminal_name:
                # Terminal boundary: fire if the completed window licenses,
                # otherwise flush everything buffered plus the terminal.
                out_names = (
                    fire(new_buf, p) if len(new_buf) == m else None
                )
                if out_names is None:
                    out_names = list(new_buf)
                next_buf: tuple[str, ...] = ()
            elif len(new_buf) < m:
                out_names = []  # still filling; emit nothing yet
                next_buf = new_buf
            else:
                fired = fire(new_buf, p)
                if fired is not None:
                    out_names = fired
                    next_buf = ()  # consume the whole window
                else:
                    out_names = [new_buf[0]]  # emit stale, slide by one
                    next_buf = new_buf[1:]

            next_tbuf, next_p = latch(tbuf, p, x_name)
            dst: State = (next_buf, next_tbuf, next_p)

            _emit_chain(
                fst,
                sym,
                src,
                labels[x_name],
                out_names,
                get_state(dst),
                w,
                rule.Id,
                max_arcs,
                arc_count,
                collapse_multisymbol_output,
            )
            if dst not in visited:
                visited.add(dst)
                queue.append(dst)

    # Accepting exactly when no INR-window is left part-built. Composition
    # against a linear acceptor only admits a path consuming all input, so
    # marking several states final is harmless.
    for (buf, _, _), state in state_map.items():
        if not buf:
            fst.set_final(state, w)

    fst.set_input_symbols(sym)
    fst.set_output_symbols(sym)
    return fst


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_rule(
    rule: Rule,
    fs: lp.FeatureSystem,
    inv: lp.Inventory,
    max_arcs: int = _DEFAULT_MAX_ARCS,
    no_epsilon_input_arcs: bool = False,
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
        no_epsilon_input_arcs: If True, multi-segment outputs are encoded as
                  single "sequence symbols" on consuming arcs, avoiding
                  epsilon-input output chains.

    Returns:
        A compiled pynini.Fst transducer.

    Raises:
        CompileError: If the rule is not compilable or exceeds max_arcs.
    """
    check_wellformed(rule)
    out_ast = dsl.parse(rule.Out)
    cnd_ast = dsl.parse(rule.Cnd) if rule.Cnd is not None else None
    # The quotient is needed for the size estimate anyway, so compute it once
    # here and hand it to the builder rather than letting it recompute.
    quotient = trm_quotient(rule, out_ast, cnd_ast, fs, inv)
    _check_size(rule, len(_all_segments(inv)), len(quotient.reps), max_arcs)
    return _compile_general(
        rule,
        out_ast,
        fs,
        inv,
        max_arcs,
        collapse_multisymbol_output=no_epsilon_input_arcs,
        cnd_ast=cnd_ast,
        quotient=quotient,
    )


def _encode_sequence_symbol(names: list[str]) -> str:
    return "".join(names)


def _esc_meta(s: str) -> str:
    s = s.replace(_SEQ_META_ESC, _SEQ_META_ESC + _SEQ_META_ESC)
    s = s.replace(_SEQ_META_SEP, _SEQ_META_ESC + _SEQ_META_SEP)
    s = s.replace(_SEQ_META_EQ, _SEQ_META_ESC + _SEQ_META_EQ)
    return s


def _unesc_meta(s: str) -> str:
    out: list[str] = []
    esc = False
    for ch in s:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == _SEQ_META_ESC:
            esc = True
            continue
        out.append(ch)
    if esc:
        out.append(_SEQ_META_ESC)
    return "".join(out)


def _split_escaped(s: str, sep: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    esc = False
    for ch in s:
        if esc:
            cur.append(ch)
            esc = False
            continue
        if ch == _SEQ_META_ESC:
            esc = True
            continue
        if ch == sep:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if esc:
        cur.append(_SEQ_META_ESC)
    parts.append("".join(cur))
    return parts


def _register_sequence_mapping(
    sym: pynini.SymbolTable,
    seq_sym: str,
    names: list[str],
) -> None:
    lhs = _esc_meta(seq_sym)
    rhs = _SEQ_META_SEP.join(_esc_meta(name) for name in names)
    map_sym = f"{_SEQ_MAP_PREFIX}{lhs}{_SEQ_META_EQ}{rhs}"
    if sym.find(map_sym) == -1:
        sym.add_symbol(map_sym)


def _sequence_symbol_map(sym: pynini.SymbolTable) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i in range(sym.num_symbols()):
        label = sym.find(i)
        if not label.startswith(_SEQ_MAP_PREFIX):
            continue
        payload = label[len(_SEQ_MAP_PREFIX) :]
        parts = _split_escaped(payload, _SEQ_META_EQ)
        if len(parts) < 2:
            continue
        lhs = _unesc_meta(parts[0])
        rhs_joined = _SEQ_META_EQ.join(parts[1:])
        rhs = [_unesc_meta(x) for x in _split_escaped(rhs_joined, _SEQ_META_SEP)]
        out[lhs] = rhs
    return out


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
    # the correct position.  BOS and EOS are stripped from the output afterward
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
    seq_map = _sequence_symbol_map(out_sym)

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
            name = out_sym.find(arc.olabel)
            result.extend(seq_map.get(name, [name]))
        state = arc.nextstate

    if rule.Dir == "R":
        result = list(reversed(result))

    # Strip the boundary markers added above.
    if has_bos and result and result[0] == _BOS_NAME:
        result = result[1:]
    if has_eos and result and result[-1] == _EOS_NAME:
        result = result[:-1]

    return result
