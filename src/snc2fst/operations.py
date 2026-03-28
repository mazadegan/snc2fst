from snc2fst.types import Segment, FeatureSpec, FeatureSpecSequence, Feature, Word


def subtract(seg: Segment, valued_features: FeatureSpec) -> Segment:
    """A \\ B = {cF | cF ∈ A ∧ cF ∉ B}"""
    remove = {(v, f) for v, f in valued_features}
    return {f: v for f, v in seg.items() if (v, f) not in remove}


def unify(seg: Segment, valued_features: FeatureSpec) -> Segment:
    """A ⊔ B = A ∪ {cF | cF ∈ B ∧ ¬cF ∉ A}"""
    result = dict(seg)
    for v, f in valued_features:
        opposite = "-" if v == "+" else "+"
        if seg.get(f) != opposite:
            result[f] = v
    return result


def project(seg: Segment, names: list[Feature]) -> Segment:
    """π_F(s) = s ∩ ({-,+} × F)"""
    return {f: v for f, v in seg.items() if f in names and v in ("+", "-")}


def in_class(seg: Segment, spec: FeatureSpec) -> bool:
    """seg ∈ N(spec) ↔ spec ⊆ seg"""
    return all(seg.get(f) == v for v, f in spec)


def models(word: Word, spec_seq: FeatureSpecSequence) -> bool:
    """w ⊨ S ↔ |w| = |S| ∧ ∀i, w_i ∈ S_i"""
    if len(word) != len(spec_seq):
        return False
    return all(in_class(seg, spec) for seg, spec in zip(word, spec_seq))
