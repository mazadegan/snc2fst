from __future__ import annotations

from dataclasses import dataclass

FeaturePolarity = str
FeatureBundle = dict[str, FeaturePolarity]
OutDslAst = object


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


def parse_out_dsl(text: str) -> OutDslAst:
    tokens = _tokenize(text)
    if not tokens:
        raise OutDslError("Out DSL expression is empty.")
    ast, next_idx = _parse_expr(tokens, 0)
    if next_idx != len(tokens):
        raise OutDslError("Unexpected tokens after expression.")
    return ast


def extract_out_features(text: str) -> set[str]:
    ast = parse_out_dsl(text)
    return _collect_features(ast)


def extract_trm_dependent_features(text: str) -> set[str]:
    ast = parse_out_dsl(text)
    return _collect_trm_dependent_features(ast)


def out_uses_full_trm(text: str) -> bool:
    ast = parse_out_dsl(text)
    return _has_bare_target(ast, "TRM") or _has_proj_star(ast, "TRM")


def out_uses_all(text: str) -> bool:
    ast = parse_out_dsl(text)
    return _has_all(ast)


def out_uses_all_inr(text: str) -> bool:
    ast = parse_out_dsl(text)
    return _has_proj_star(ast, "INR")


def out_uses_all_trm(text: str) -> bool:
    ast = parse_out_dsl(text)
    return _has_proj_star(ast, "TRM")


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

    if op == "bundle":
        return _eval_bundle(node, context)
    if op == "proj":
        return _eval_proj(node, context)
    if op == "unify":
        return _eval_unify(node, context)
    if op == "subtract":
        return _eval_subtract(node, context)

    raise OutDslError(f"Unknown operator: {op!r}")


def _collect_features(node: OutDslAst) -> set[str]:
    if isinstance(node, str):
        if node in {"INR", "TRM"}:
            return set()
        raise OutDslError(f"Unknown atom: {node!r}")
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")

    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")

    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return _collect_bundle_features(node)
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        bundle_features = _collect_features(node[1])
        feature_list = node[2]
        if feature_list == "*":
            return bundle_features
        if not isinstance(feature_list, list):
            raise OutDslError("proj expects a feature list or '*'.")
        listed: set[str] = set()
        for item in feature_list:
            if not isinstance(item, str) or not item.strip():
                raise OutDslError("Feature list entries must be symbols.")
            listed.add(item)
        return bundle_features | listed
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        left = _collect_features(node[1])
        right = _collect_features(node[2])
        return left | right

    raise OutDslError(f"Unknown operator: {op!r}")


def _collect_bundle_features(node: list[object]) -> set[str]:
    listed: set[str] = set()
    for item in node[1:]:
        if not isinstance(item, list) or len(item) != 2:
            raise OutDslError("bundle entries must be (+ Feature) or (- Feature).")
        polarity, feature = item
        if polarity not in {"+", "-"}:
            raise OutDslError("bundle polarity must be '+' or '-'.")
        if not isinstance(feature, str) or not feature.strip():
            raise OutDslError("bundle feature must be a non-empty symbol.")
        listed.add(feature)
    return listed


def _collect_trm_dependent_features(node: OutDslAst) -> set[str]:
    return _collect_trm_dependent_features_inner(
        node, trm_context=_has_trm(node)
    )[0]


def _collect_trm_dependent_features_inner(
    node: OutDslAst, *, trm_context: bool
) -> tuple[set[str], bool]:
    if isinstance(node, str):
        if node == "TRM":
            return set(), True
        if node == "INR":
            return set(), False
        raise OutDslError(f"Unknown atom: {node!r}")

    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")

    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")

    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        features = _collect_bundle_features(node)
        return (features if trm_context else set()), False

    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        bundle = node[1]
        feature_list = node[2]
        if feature_list == "*":
            feature_list = []
        elif not isinstance(feature_list, list):
            raise OutDslError("proj expects a feature list or '*'.")
        listed: set[str] = set()
        if feature_list:
            for item in feature_list:
                if not isinstance(item, str) or not item.strip():
                    raise OutDslError("Feature list entries must be symbols.")
                listed.add(item)
        bundle_features, bundle_has_trm = _collect_trm_dependent_features_inner(
            bundle, trm_context=trm_context
        )
        trm_features = set(bundle_features)
        if bundle_has_trm:
            trm_features |= listed
        return trm_features, bundle_has_trm

    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        left_has_trm = _has_trm(node[1])
        right_has_trm = _has_trm(node[2])
        has_trm_here = left_has_trm or right_has_trm
        left_features, _ = _collect_trm_dependent_features_inner(
            node[1], trm_context=trm_context or has_trm_here
        )
        right_features, _ = _collect_trm_dependent_features_inner(
            node[2], trm_context=trm_context or has_trm_here
        )
        return left_features | right_features, has_trm_here

    raise OutDslError(f"Unknown operator: {op!r}")


def _has_trm(node: OutDslAst) -> bool:
    if isinstance(node, str):
        if node in {"TRM", "INR"}:
            return node == "TRM"
        raise OutDslError(f"Unknown atom: {node!r}")
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return False
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        return _has_trm(node[1])
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        return _has_trm(node[1]) or _has_trm(node[2])
    raise OutDslError(f"Unknown operator: {op!r}")


def _has_unprojected_trm(
    node: OutDslAst, *, projected: bool
) -> bool:
    if isinstance(node, str):
        if node == "TRM":
            return not projected
        if node == "INR":
            return False
        raise OutDslError(f"Unknown atom: {node!r}")
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return False
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        return _has_unprojected_trm(node[1], projected=True)
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        return _has_unprojected_trm(
            node[1], projected=projected
        ) or _has_unprojected_trm(node[2], projected=projected)
    raise OutDslError(f"Unknown operator: {op!r}")


def _has_all(node: OutDslAst) -> bool:
    if isinstance(node, str):
        if node in {"TRM", "INR"}:
            return False
        raise OutDslError(f"Unknown atom: {node!r}")
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return False
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        return _has_all(node[1]) or node[2] == "*"
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        return _has_all(node[1]) or _has_all(node[2])
    raise OutDslError(f"Unknown operator: {op!r}")


def _has_bare_target(node: OutDslAst, target: str, *, in_proj: bool = False) -> bool:
    if isinstance(node, str):
        return node == target and not in_proj
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return False
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        return _has_bare_target(node[1], target, in_proj=True)
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        return _has_bare_target(node[1], target, in_proj=in_proj) or _has_bare_target(
            node[2], target, in_proj=in_proj
        )
    raise OutDslError(f"Unknown operator: {op!r}")


def _has_proj_star(node: OutDslAst, target: str) -> bool:
    if isinstance(node, str):
        return False
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "bundle":
        if len(node) < 2:
            raise OutDslError("bundle expects one or more pairs.")
        return False
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        bundle = node[1]
        feature_list = node[2]
        if feature_list == "*" and _bundle_is_target(bundle, target):
            return True
        return _has_proj_star(bundle, target)
    if op in {"unify", "subtract"}:
        if len(node) != 3:
            raise OutDslError(f"{op} expects 2 arguments.")
        return _has_proj_star(node[1], target) or _has_proj_star(node[2], target)
    raise OutDslError(f"Unknown operator: {op!r}")


def _bundle_is_target(node: OutDslAst, target: str) -> bool:
    if isinstance(node, str):
        return node == target
    if not isinstance(node, list) or not node:
        raise OutDslError("Invalid expression.")
    op = node[0]
    if not isinstance(op, str):
        raise OutDslError("Operator must be a symbol.")
    if op == "proj":
        if len(node) != 3:
            raise OutDslError("proj expects 2 arguments.")
        return _bundle_is_target(node[1], target)
    if op in {"unify", "subtract", "bundle"}:
        return False
    raise OutDslError(f"Unknown operator: {op!r}")


def _eval_bundle(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) < 2:
        raise OutDslError("bundle expects one or more pairs.")
    result: FeatureBundle = {}
    for item in node[1:]:
        if not isinstance(item, list) or len(item) != 2:
            raise OutDslError("bundle entries must be (+ Feature) or (- Feature).")
        polarity, feature = item
        if polarity not in {"+", "-"}:
            raise OutDslError("bundle polarity must be '+' or '-'.")
        if not isinstance(feature, str) or not feature.strip():
            raise OutDslError("bundle feature must be a non-empty symbol.")
        if feature not in context.features:
            raise OutDslError(f"Unknown feature: {feature!r}")
        if feature in result and result[feature] != polarity:
            continue
        result[feature] = polarity
    return result


def _eval_proj(node: list[object], context: OutDslContext) -> FeatureBundle:
    if len(node) != 3:
        raise OutDslError("proj expects 2 arguments.")
    bundle = _eval(node[1], context)
    feature_list = node[2]
    if feature_list == "*":
        return dict(bundle)
    if not isinstance(feature_list, list):
        raise OutDslError("proj expects a feature list or '*'.")
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
