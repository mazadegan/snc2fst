from __future__ import annotations

from typing import Iterable

from .feature_analysis import compute_v_features
from .out_dsl import evaluate_out_dsl
from .rules import Rule
from .tuple_utils import (
    BundleTuple,
    bundle_from_tuple,
    compile_class_predicate,
    tuple_from_bundle,
)


def evaluate_rule_on_bundles(
    rule: Rule, segments: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    v_order = tuple(sorted(compute_v_features(rule)))
    tuple_segments = [
        tuple_from_bundle(segment, v_order) for segment in segments
    ]
    result = evaluate_rule_on_tuples(rule, tuple_segments, v_order)
    return [bundle_from_tuple(bundle, v_order) for bundle in result]


def evaluate_rule_on_bundles_with_order(
    rule: Rule,
    segments: Iterable[dict[str, str]],
    v_order: tuple[str, ...],
) -> list[dict[str, str]]:
    tuple_segments = [
        tuple_from_bundle(segment, v_order) for segment in segments
    ]
    result = evaluate_rule_on_tuples(rule, tuple_segments, v_order)
    return [bundle_from_tuple(bundle, v_order) for bundle in result]


def evaluate_rule_on_tuples(
    rule: Rule, segments: Iterable[BundleTuple], v_order: tuple[str, ...]
) -> list[BundleTuple]:
    v_features = set(v_order)
    v_index = {feature: idx for idx, feature in enumerate(v_order)}
    is_inr = compile_class_predicate(rule.inr, v_index)
    is_trm = compile_class_predicate(rule.trm, v_index)
    is_cnd = compile_class_predicate(rule.cnd, v_index)

    segment_list = list(segments)
    output = list(segment_list)
    trm_bundle: BundleTuple | None = None

    if rule.dir == "RIGHT":
        indices = range(len(segment_list) - 1, -1, -1)
    else:
        indices = range(len(segment_list))

    for idx in indices:
        segment = segment_list[idx]
        if is_inr(segment) and trm_bundle is not None:
            inr_bundle = bundle_from_tuple(segment, v_order)
            trm_dict = bundle_from_tuple(trm_bundle, v_order)
            out_bundle = evaluate_out_dsl(
                rule.out, inr=inr_bundle, trm=trm_dict, features=v_features
            )
            output[idx] = tuple_from_bundle(out_bundle, v_order)

        if is_trm(segment):
            if is_cnd(segment):
                trm_bundle = segment
            else:
                trm_bundle = None

    return output
