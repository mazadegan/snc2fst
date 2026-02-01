from __future__ import annotations

from dataclasses import dataclass

FeaturePolarity = str
FeatureBundle = dict[str, FeaturePolarity]


class OutDslError(ValueError):
    pass


@dataclass(frozen=True)
class OutDslContext:
    inr: FeatureBundle
    trm: FeatureBundle
    features: set[str]


def evaluate_out_dsl(
    text: str,
    *,
    inr: FeatureBundle,
    trm: FeatureBundle,
    features: set[str],
) -> FeatureBundle:
    tokens = _tokenize(text)
    if not tokens:
        raise OutDslError("Out DSL expression is empty.")
    ast, next_idx = _parse_expr(tokens, 0)
    if next_idx != len(tokens):
        raise OutDslError("Unexpected tokens after expression.")
    context = OutDslContext(
        inr=_validate_bundle(inr),
        trm=_validate_bundle(trm),
        features=features,
    )
    return _eval(ast, context)


def _validate_bundle(bundle: FeatureBundle) -> FeatureBundle:
    for feature, polarity in bundle.items():
        if polarity not in {"+", "-"}:
            raise OutDslError(
                f"Invalid feature polarity for {feature!r}: {polarity!r}"
            )
        if not feature.strip():
            raise OutDslError("Feature names cannot be empty.")
    return dict(bundle)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch in ("(", ")"):
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(ch)
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_expr(tokens: list[str], start: int) -> tuple[object, int]:
    if start >= len(tokens):
        raise OutDslError("Unexpected end of expression.")
    token = tokens[start]
    if token == "(":
        items: list[object] = []
        idx = start + 1
        while idx < len(tokens) and tokens[idx] != ")":
            item, idx = _parse_expr(tokens, idx)
            items.append(item)
        if idx >= len(tokens) or tokens[idx] != ")":
            raise OutDslError("Unclosed list in expression.")
        return items, idx + 1
    if token == ")":
        raise OutDslError("Unexpected ')'.")
    return token, start + 1


def _eval(node: object, context: OutDslContext) -> FeatureBundle:
    if isinstance(node, str):
        if node == "INR":
            return dict(context.inr)
        if node == "TRM":
            return dict(context.trm)
        raise OutDslError(f"Unknown atom: {node!r}")

    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")

    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")

    if op == "lit":
        return _eval_lit(node, context)
    if op == "proj":
        return _eval_proj(node, context)
    if op == "unify":
        return _eval_unify(node, context)
    if op == "subtract":
        return _eval_subtract(node, context)

    raise OutDslError(f"Unknown operator: {op!r}")


def _eval_lit(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) != 3:
        raise OutDslError("lit expects 2 arguments.")
    polarity = node[1]
    feature = node[2]
    if polarity not in {"+", "-"}:
        raise OutDslError("lit polarity must be '+' or '-'.")
    if not isinstance(feature, str) or not feature.strip():
        raise OutDslError("lit feature must be a non-empty symbol.")
    if feature not in context.features:
        raise OutDslError(f"Unknown feature: {feature!r}")
    return {feature: polarity}


def _eval_proj(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) != 3:
        raise OutDslError("proj expects 2 arguments.")
    bundle = _eval(node[1], context)
    feature_list = node[2]
    if not isinstance(feature_list, list):
        raise OutDslError("proj expects a feature list.")
    features: list[str] = []
    for item in feature_list:
        if not isinstance(item, str) or not item.strip():
            raise OutDslError("Feature list entries must be symbols.")
        if item not in context.features:
            raise OutDslError(f"Unknown feature: {item!r}")
        features.append(item)
    if not features:
        return {}
    return {feature: bundle[feature] for feature in features if feature in bundle}


def _eval_unify(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) != 3:
        raise OutDslError("unify expects 2 arguments.")
    left = _eval(node[1], context)
    right = _eval(node[2], context)
    result = dict(left)
    for feature, polarity in right.items():
        if feature in result and result[feature] != polarity:
            continue
        if feature not in result:
            result[feature] = polarity
    return result


def _eval_subtract(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) != 3:
        raise OutDslError("subtract expects 2 arguments.")
    left = _eval(node[1], context)
    right = _eval(node[2], context)
    result = dict(left)
    for feature, polarity in right.items():
        if feature in result and result[feature] == polarity:
            del result[feature]
    return result
