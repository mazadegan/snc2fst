from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from .feature_analysis import compute_p_features, compute_v_features
from .out_dsl import evaluate_out_dsl
from .rules import Rule

TernaryValue = int
BundleTuple = tuple[TernaryValue, ...]


@dataclass(frozen=True)
class TvMachine:
    v_order: tuple[str, ...]
    p_order: tuple[str, ...]
    start_state: int
    final_states: set[int]
    arcs: list[tuple[int, int, int, int]]


def compile_tv(
    rule: Rule,
    *,
    show_progress: bool = False,
    v_features: set[str] | None = None,
    p_features: set[str] | None = None,
) -> TvMachine:
    v_features = v_features if v_features is not None else compute_v_features(rule)
    p_features = p_features if p_features is not None else compute_p_features(rule)
    v_order = tuple(sorted(v_features))
    p_order = tuple(feature for feature in v_order if feature in p_features)

    v_index = {feature: idx for idx, feature in enumerate(v_order)}
    p_indices = tuple(v_index[feature] for feature in p_order)

    sigma_v = list(_enumerate_sigma(len(v_order)))
    sigma_p = list(_enumerate_sigma(len(p_order)))

    is_inr = _compile_class_predicate(rule.inr, v_index)
    is_trm = _compile_class_predicate(rule.trm, v_index)
    is_cnd = _compile_class_predicate(rule.cnd, v_index)

    q_false = 0
    trm_state = {p: idx + 1 for idx, p in enumerate(sigma_p)}
    arcs: list[tuple[int, int, int, int]] = []

    def emit(x_v: BundleTuple, trm_p: BundleTuple | None) -> BundleTuple:
        if not is_inr(x_v):
            return x_v
        inr_bundle = _bundle_from_tuple(x_v, v_order)
        trm_bundle = (
            _bundle_from_tuple(trm_p, p_order) if trm_p is not None else {}
        )
        out_bundle = evaluate_out_dsl(
            rule.out, inr=inr_bundle, trm=trm_bundle, features=v_features
        )
        return _tuple_from_bundle(out_bundle, v_order)

    states = [(q_false, None)] + [
        (state_id, trm_p) for trm_p, state_id in trm_state.items()
    ]
    total_arcs = len(states) * len(sigma_v)
    pbar = None
    if show_progress and total_arcs:
        try:
            from tqdm import tqdm
        except ImportError:  # pragma: no cover - dependency missing
            pbar = None
        else:
            pbar = tqdm(total=total_arcs, desc="arcs (total)")

    for state_id, trm_p in states:
        for x_v in sigma_v:
            ilabel = _encode_label(x_v)
            if state_id == q_false:
                if is_trm(x_v) and is_cnd(x_v):
                    next_state = trm_state[_project_tuple(x_v, p_indices)]
                else:
                    next_state = q_false
                out_tuple = x_v
            else:
                if is_trm(x_v):
                    if is_cnd(x_v):
                        next_state = trm_state[_project_tuple(x_v, p_indices)]
                    else:
                        next_state = q_false
                else:
                    next_state = state_id
                out_tuple = emit(x_v, trm_p)
            olabel = _encode_label(out_tuple)
            arcs.append((state_id, ilabel, olabel, next_state))
        if pbar is not None:
            pbar.update(len(sigma_v))

    if pbar is not None:
        pbar.close()

    final_states = set(range(1 + len(sigma_p)))
    return TvMachine(
        v_order=v_order,
        p_order=p_order,
        start_state=q_false,
        final_states=final_states,
        arcs=arcs,
    )


def write_att(
    machine: TvMachine, output_path: str, *, symtab_path: str | None = None
) -> None:
    with open(output_path, "w", encoding="utf-8") as handle:
        for src, ilabel, olabel, dst in machine.arcs:
            handle.write(f"{src} {dst} {ilabel} {olabel} 0\n")
        for state in sorted(machine.final_states):
            handle.write(f"{state} 0\n")

    if symtab_path is not None:
        _write_symtab(machine, symtab_path)


def run_tv_machine(
    machine: TvMachine, inputs: list[BundleTuple]
) -> list[BundleTuple]:
    transitions: dict[tuple[int, int], tuple[int, int]] = {}
    for src, ilabel, olabel, dst in machine.arcs:
        transitions[(src, ilabel)] = (dst, olabel)

    state = machine.start_state
    outputs: list[BundleTuple] = []
    for bundle in inputs:
        ilabel = _encode_label(bundle)
        key = (state, ilabel)
        if key not in transitions:
            raise ValueError(
                f"Missing transition for state {state} label {ilabel}."
            )
        next_state, olabel = transitions[key]
        outputs.append(_decode_label(olabel, len(machine.v_order)))
        state = next_state
    return outputs


def _enumerate_sigma(size: int) -> list[BundleTuple]:
    return [tuple(values) for values in product((0, 1, 2), repeat=size)]


def _encode_label(bundle: BundleTuple) -> int:
    label = 1
    base = 1
    for value in bundle:
        label += value * base
        base *= 3
    return label


def _decode_label(label: int, size: int) -> BundleTuple:
    if label <= 0:
        raise ValueError(f"Invalid label: {label}")
    value = label - 1
    digits: list[int] = []
    for _ in range(size):
        digits.append(value % 3)
        value //= 3
    return tuple(digits)


def _project_tuple(bundle: BundleTuple, indices: tuple[int, ...]) -> BundleTuple:
    return tuple(bundle[idx] for idx in indices)


def _bundle_from_tuple(
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


def _write_symtab(machine: TvMachine, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("<eps> 0\n")
        for bundle in _enumerate_sigma(len(machine.v_order)):
            label = _encode_label(bundle)
            symbol = _symbol_for_bundle(bundle, machine.v_order)
            handle.write(f"{symbol} {label}\n")


def _symbol_for_bundle(
    bundle: BundleTuple, features: tuple[str, ...]
) -> str:
    parts: list[str] = []
    for feature, value in zip(features, bundle):
        if value == 1:
            suffix = "+"
        elif value == 2:
            suffix = "-"
        else:
            suffix = "0"
        parts.append(f"{feature}{suffix}")
    return "_".join(parts)
