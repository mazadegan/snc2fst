from __future__ import annotations

from typing import Iterable

from .feature_analysis import compute_v_features
from .out_dsl import evaluate_out_dsl
from .rules import Rule

TernaryValue = int
BundleTuple = tuple[TernaryValue, ...]


def evaluate_rule_on_bundles(
    rule: Rule, segments: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    v_order = tuple(sorted(compute_v_features(rule)))
    tuple_segments = [
        _tuple_from_bundle(segment, v_order) for segment in segments
    ]
    result = evaluate_rule_on_tuples(rule, tuple_segments, v_order)
    return [_bundle_from_tuple(bundle, v_order) for bundle in result]


def evaluate_rule_on_tuples(
    rule: Rule, segments: Iterable[BundleTuple], v_order: tuple[str, ...]
) -> list[BundleTuple]:
    v_features = set(v_order)
    v_index = {feature: idx for idx, feature in enumerate(v_order)}
    is_inr = _compile_class_predicate(rule.inr, v_index)
    is_trm = _compile_class_predicate(rule.trm, v_index)
    is_cnd = _compile_class_predicate(rule.cnd, v_index)

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
            inr_bundle = _bundle_from_tuple(segment, v_order)
            trm_dict = _bundle_from_tuple(trm_bundle, v_order)
            out_bundle = evaluate_out_dsl(
                rule.out, inr=inr_bundle, trm=trm_dict, features=v_features
            )
            output[idx] = _tuple_from_bundle(out_bundle, v_order)

        if is_trm(segment):
            if is_cnd(segment):
                trm_bundle = segment
            else:
                trm_bundle = None

    return output


def _bundle_from_tuple(
    bundle: BundleTuple, features: tuple[str, ...]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for feature, value in zip(features, bundle):
        if value == 1:
            result[feature] = "+"
        elif value == 2:
            result[feature] = "-"
    return result


def _tuple_from_bundle(
    bundle: dict[str, str], features: tuple[str, ...]
) -> BundleTuple:
    values: list[int] = []
    for feature in features:
        polarity = bundle.get(feature)
        if polarity == "+":
            values.append(1)
        elif polarity == "-":
            values.append(2)
        else:
            values.append(0)
    return tuple(values)


def _compile_class_predicate(
    feature_class: list[tuple[str, str]],
    v_index: dict[str, int],
) -> callable:
    if not feature_class:
        return lambda _bundle: True

    requirements: list[tuple[int, int]] = []
    for polarity, feature in feature_class:
        idx = v_index[feature]
        value = 1 if polarity == "+" else 2
        requirements.append((idx, value))

    def _predicate(bundle: BundleTuple) -> bool:
        return all(bundle[idx] == value for idx, value in requirements)

    return _predicate
