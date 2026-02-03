from __future__ import annotations

from .out_dsl import (
    extract_out_features,
    extract_trm_dependent_features,
    out_uses_all_inr,
    out_uses_all_trm,
    out_uses_full_trm,
)
from .rules import Rule


def compute_v_features(
    rule: Rule, *, alphabet_features: set[str] | None = None
) -> set[str]:
    if alphabet_features is not None and (
        out_uses_all_inr(rule.out) or out_uses_all_trm(rule.out)
    ):
        return set(alphabet_features)
    features: set[str] = set()
    for label in ("inr", "trm", "cnd"):
        for _, feature in getattr(rule, label):
            features.add(feature)
    features |= extract_out_features(rule.out)
    return features


def compute_p_features(
    rule: Rule, *, alphabet_features: set[str] | None = None
) -> set[str]:
    if alphabet_features is not None and out_uses_all_trm(rule.out):
        return set(alphabet_features)
    if out_uses_full_trm(rule.out):
        return compute_v_features(rule, alphabet_features=alphabet_features)
    return extract_trm_dependent_features(rule.out)
