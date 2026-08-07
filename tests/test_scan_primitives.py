"""Unit tests for the direction-parameterized scanning primitives.

The invariant under test: buffers and the output sink are always in *word
order*, whichever direction the scan runs in.
"""

import logical_phonology as lp
import pytest

from snc2fst.evaluator import _Ring, _scan_order, _Sink

FS = lp.FeatureSystem(frozenset(["F", "G"]))
A = FS.segment({"F": lp.POS, "G": lp.POS})
B = FS.segment({"F": lp.POS, "G": lp.NEG})
C = FS.segment({"F": lp.NEG, "G": lp.POS})


def names(ring_or_sink) -> list[lp.Segment]:
    return list(ring_or_sink.items)


# ---------------------------------------------------------------------------
# scan order
# ---------------------------------------------------------------------------


def test_scan_order_left_is_ascending():
    assert list(_scan_order(4, right=False)) == [0, 1, 2, 3]


def test_scan_order_right_is_descending():
    assert list(_scan_order(4, right=True)) == [3, 2, 1, 0]


def test_scan_order_empty():
    assert list(_scan_order(0, right=True)) == []
    assert list(_scan_order(0, right=False)) == []


# ---------------------------------------------------------------------------
# _Ring — word order is preserved under both directions
# ---------------------------------------------------------------------------


def test_push_left_keeps_word_order():
    """Dir=L scans 0,1,2 so pushing A,B,C must yield <A,B,C>."""
    ring = _Ring(right=False)
    for seg in (A, B, C):
        ring.push(seg)
    assert names(ring) == [A, B, C]


def test_push_right_keeps_word_order():
    """Dir=R scans 2,1,0 so pushing C,B,A must also yield <A,B,C>."""
    ring = _Ring(right=True)
    for seg in (C, B, A):
        ring.push(seg)
    assert names(ring) == [A, B, C]


def test_stale_is_the_earliest_scanned_segment():
    left = _Ring(right=False)
    for seg in (A, B, C):
        left.push(seg)
    assert left.stale() == A  # scanned first

    right = _Ring(right=True)
    for seg in (C, B, A):
        right.push(seg)
    assert right.stale() == C  # scanned first


def test_drop_stale_slides_the_window():
    left = _Ring(right=False)
    for seg in (A, B, C):
        left.push(seg)
    left.drop_stale()
    assert names(left) == [B, C]

    right = _Ring(right=True)
    for seg in (C, B, A):
        right.push(seg)
    right.drop_stale()
    assert names(right) == [A, B]


def test_slide_then_push_reconstitutes_the_next_window():
    """The whole point of a slide: keep m-1 segments and add the next one."""
    ring = _Ring(right=False)
    for seg in (A, B):
        ring.push(seg)
    ring.drop_stale()
    ring.push(C)
    assert names(ring) == [B, C]


def test_clear_and_len():
    ring = _Ring(right=True)
    assert len(ring) == 0
    ring.push(A)
    ring.push(B)
    assert len(ring) == 2
    ring.clear()
    assert len(ring) == 0
    assert names(ring) == []


def test_word_is_in_word_order():
    ring = _Ring(right=True)
    for seg in (C, B, A):
        ring.push(seg)
    assert list(ring.word(FS)) == [A, B, C]


def test_drop_stale_on_empty_raises():
    with pytest.raises(IndexError):
        _Ring(right=False).drop_stale()


# ---------------------------------------------------------------------------
# _Sink — emissions concatenate in increasing position order
# ---------------------------------------------------------------------------


def test_sink_left_appends():
    sink = _Sink(right=False)
    sink.emit([A])
    sink.emit([B, C])
    assert list(sink.word(FS)) == [A, B, C]


def test_sink_right_prepends():
    """Scanning right-to-left, the later emission is the earlier position."""
    sink = _Sink(right=True)
    sink.emit([C])
    sink.emit([A, B])
    assert list(sink.word(FS)) == [A, B, C]


def test_sink_empty_emission_is_a_noop():
    sink = _Sink(right=True)
    sink.emit([A])
    sink.emit([])
    sink.emit([B])
    assert list(sink.word(FS)) == [B, A]


def test_sink_starts_empty():
    assert list(_Sink(right=True).word(FS)) == []
    assert list(_Sink(right=False).word(FS)) == []
