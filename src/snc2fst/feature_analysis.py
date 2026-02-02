from __future__ import annotations

from .out_dsl import (
    extract_out_features,
    extract_trm_dependent_features,
    out_uses_full_trm,
)
from .rules import Rule


def compute_v_features(rule: Rule) -> set[str]:
    features: set[str] = set()
    for label in ("inr", "trm", "cnd"):
        for _, feature in getattr(rule, label):
            features.add(feature)
    features |= extract_out_features(rule.out)
    return features


def compute_p_features(rule: Rule) -> set[str]:
    if out_uses_full_trm(rule.out):
        return compute_v_features(rule)
    return extract_trm_dependent_features(rule.out)
