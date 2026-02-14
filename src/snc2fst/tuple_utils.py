from __future__ import annotations

TernaryValue = int
BundleTuple = tuple[TernaryValue, ...]


def bundle_from_tuple(
    bundle: BundleTuple | None, features: tuple[str, ...]
) -> dict[str, str]:
    if bundle is None:
        return {}
    result: dict[str, str] = {}
    for feature, value in zip(features, bundle):
        if value == 1:
            result[feature] = "+"
        elif value == 2:
            result[feature] = "-"
    return result


def tuple_from_bundle(
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


def compile_class_predicate(
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
