"""Rule-level well-formedness: the non-overlap condition.

A sequence-generalized S&C rule is evaluated by sliding an ``m``-buffer to
detect Inr-matches while maintaining a pointer to the nearest Trm-match
(see ``evaluator.apply_rule``).  For that single pass to be well defined, an
Inr-window and a Trm-window must never share a position — otherwise some
segment would have to be read under two roles at once, both as part of the
replaceable target span and as part of the licensing evidence.

*Non-overlap* is the rule-level condition that rules this out.  It is a pure
function of ``Inr``, ``Trm`` and ``Dir``, checkable in ``O(mn)`` feature
comparisons at grammar-load time, independent of any input word.

Throughout, ``m = len(Inr)`` and ``n = len(Trm)``.

This module deliberately has no pynini dependency, so that ``apply_rule`` and
``snc2fst validate`` keep working in an install without it.
"""

from __future__ import annotations

from snc2fst.errors import CompileError
from snc2fst.models import Rule

# A feature specification as parsed by ``models.Rule``: (sign, name) pairs
# with sign in {"+", "-", "*"}.
Spec = list[tuple[str, str]]

# Feature names reserved by logical_phonology for the boundary pseudo-segments.
# A segment satisfying [+BOS] is *exactly* fs.BOS, whose feature set is the
# singleton {BOS: +}; likewise for EOS.  User feature sets can never contain
# these names (logical_phonology rejects them), so the reasoning in
# ``_boundary_excludes`` is sound.
_BOUNDARY_FEATURES = ("BOS", "EOS")


def offsets_to_check(m: int, n: int, direction: str) -> list[int]:
    """Return the offsets ``d = k - i`` a well-formed rule must exclude.

    ``i`` is the start of an Inr-window and ``k`` the start of a Trm-window.
    Which offsets matter is governed by two effects together: the offsets the
    search can actually reach, and the offsets at which a Trm-match is latched
    into the pointer before the firing test — even one the search itself
    ignores.

    For ``Dir = "R"`` these coincide, so only ``{1, ..., m-1}`` matters.  For
    ``Dir = "L"`` they do not: a Trm-window latches when its *right* end is
    scanned, so at the firing test the pointer may already hold matches lying
    inside the Inr-window, at nonnegative offsets the search must never
    consult.

    Returns the empty list when ``n == 0``: with no Trm-window there is
    nothing to overlap with, and the slot range checked for each offset would
    be empty, which would otherwise reject every ``Trm = []`` rule.

    Note: for ``Dir = "L"`` with ``m < n`` this set is *conservative*.  The
    operationally reachable overlap band is ``d in [1-n, m-n-1]``, which is
    empty when ``m < n``, but the negative offsets are what make the
    declarative search and the streaming pointer coincide, so they are kept.
    """
    if n == 0:
        return []
    if direction == "R":
        return list(range(1, m))  # {1, ..., m-1}
    # {-(n-1), ..., -1} u {0, ..., m-n-1}; the latter is empty unless m >= n+1
    return list(range(-(n - 1), 0)) + list(range(0, m - n))


def _demands(spec: Spec, name: str) -> bool:
    """True iff ``spec`` constrains feature ``name`` at all (+, - or *)."""
    return any(fname == name for _, fname in spec)


def _boundary_excludes(a: Spec, b: Spec) -> bool:
    """True iff ``a`` pins a boundary segment that cannot also satisfy ``b``.

    A slot demanding ``+BOS`` is satisfied only by the BOS pseudo-segment,
    whose entire feature set is ``{BOS: +}``.  So it is jointly satisfiable
    with ``b`` only if ``b`` constrains nothing but ``BOS`` positively.  Any
    other demand in ``b`` — a different feature, or ``-BOS`` — makes the two
    slots disjoint.  Likewise for EOS.

    This is a strengthening of the plain ``+f``/``-f`` clash test.  It only
    ever declares *more* pairs incompatible, and only where the intersection
    really is empty, so it accepts more rules without accepting an unsound
    one.
    """
    for boundary in _BOUNDARY_FEATURES:
        if ("+", boundary) not in a:
            continue
        # ``a`` pins the boundary segment; ``b`` must demand nothing else.
        if any(entry != ("+", boundary) for entry in b):
            return True
    return False


def specs_incompatible(a: Spec, b: Spec) -> bool:
    """True iff no single segment can satisfy both specifications.

    Two specifications are *compatible* iff their union is consistent, i.e.
    iff there is no feature valued ``+`` in one and ``-`` in the other.  A
    ``*`` entry expands to the union of the ``+`` and ``-`` classes (see
    ``models.Rule._as_ncs``), so it is satisfiable either way and never
    clashes with a valued slot — but it does count as *demanding* the feature,
    which matters against a boundary slot.

    Being wrong in the conservative direction (reporting compatible when the
    intersection is in fact empty) only causes a well-formed rule to be
    rejected; it can never let an ill-formed one through.
    """
    positive_a = {name for sign, name in a if sign == "+"}
    negative_a = {name for sign, name in a if sign == "-"}
    positive_b = {name for sign, name in b if sign == "+"}
    negative_b = {name for sign, name in b if sign == "-"}
    if positive_a & negative_b or negative_a & positive_b:
        return True
    return _boundary_excludes(a, b) or _boundary_excludes(b, a)


def wellformedness_errors(rule: Rule) -> list[str]:
    """Return a list of well-formedness problems with ``rule`` (empty if OK).

    This is the accumulating form and the single source of truth;
    ``check_wellformed`` is a thin raising wrapper over it.
    """
    errors: list[str] = []
    m, n = len(rule.Inr), len(rule.Trm)

    if m == 0:
        # With an empty Inr the target buffer never reaches capacity, so no
        # window is ever resolved and the rule silently becomes a no-op.
        errors.append(
            f"Rule '{rule.Id}': Inr is empty (m=0); "
            "Inr must contain at least one natural class."
        )
        return errors

    for d in offsets_to_check(m, n, rule.Dir):
        # Position i+j-1 of the Inr-window is position k+(j-d)-1 of the
        # Trm-window, so the shared slot pairs at offset d are
        # (Inr[j], Trm[j-d]) for j in the range below.
        lo, hi = max(1, 1 + d), min(m, n + d)
        blocked = any(
            specs_incompatible(rule.Inr[j - 1], rule.Trm[j - d - 1])
            for j in range(lo, hi + 1)
        )
        if not blocked:
            errors.append(
                f"Rule '{rule.Id}': Inr and Trm can overlap at offset {d} "
                f"(Inr slots {lo}-{hi} align with Trm slots "
                f"{lo - d}-{hi - d}). At least one aligned pair of natural "
                "classes must be featurally incompatible."
            )

    return errors


def check_wellformed(
    rule: Rule, exc: type[Exception] = CompileError
) -> None:
    """Raise ``exc`` if ``rule`` is not well-formed.

    Built on ``wellformedness_errors`` so the raising and accumulating forms
    agree by construction.
    """
    errors = wellformedness_errors(rule)
    if errors:
        raise exc(" ".join(errors))
