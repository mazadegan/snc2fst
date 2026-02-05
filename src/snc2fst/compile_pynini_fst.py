from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import typer

from .feature_analysis import compute_p_features, compute_v_features
from .out_dsl import evaluate_out_dsl
from .rules import Rule

TernaryValue = int
BundleTuple = tuple[TernaryValue, ...]


@dataclass(frozen=True)
class PyniniMachine:
    fst: object
    v_order: tuple[str, ...]
    p_order: tuple[str, ...]


def compile_pynini_fst(
    rule: Rule,
    *,
    show_progress: bool = False,
    v_features: set[str] | None = None,
    p_features: set[str] | None = None,
) -> PyniniMachine:
    try:
        import pywrapfst as fst
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise typer.BadParameter(
            "Pynini/pywrapfst not available; install pynini to use --pynini."
        ) from exc

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

    fst_machine = fst.VectorFst()
    for _ in range(1 + len(sigma_p)):
        fst_machine.add_state()
    fst_machine.set_start(q_false)
    weight = fst.Weight.one(fst_machine.weight_type())
    for state in range(1 + len(sigma_p)):
        fst_machine.set_final(state, weight)

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
            fst_machine.add_arc(
                state_id, fst.Arc(ilabel, olabel, weight, next_state)
            )
        if pbar is not None:
            pbar.update(len(sigma_v))

    if pbar is not None:
        pbar.close()

    return PyniniMachine(
        fst=fst_machine,
        v_order=v_order,
        p_order=p_order,
    )


def write_pynini_fst(
    rule: Rule,
    fst_path: Path,
    *,
    show_progress: bool = False,
    v_features: set[str] | None = None,
    p_features: set[str] | None = None,
) -> None:
    machine = compile_pynini_fst(
        rule,
        show_progress=show_progress,
        v_features=v_features,
        p_features=p_features,
    )
    machine.fst.write(str(fst_path))


def write_att_pynini(
    machine: PyniniMachine,
    output_path: Path,
    *,
    symtab_path: Path | None = None,
) -> None:
    try:
        import pywrapfst as fst
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise typer.BadParameter(
            "Pynini/pywrapfst not available; install pynini to use --pynini."
        ) from exc

    lines: list[str] = []
    arc_count = 0
    for state in machine.fst.states():
        for arc in machine.fst.arcs(state):
            lines.append(
                f"{state} {arc.nextstate} {arc.ilabel} {arc.olabel} 0"
            )
            arc_count += 1
    zero = fst.Weight.zero(machine.fst.weight_type())
    for state in machine.fst.states():
        if machine.fst.final(state) != zero:
            lines.append(f"{state} 0")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if symtab_path is not None:
        _write_symtab(machine, symtab_path)


def evaluate_with_pynini(
    *,
    rule: Rule,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
    v_features: set[str] | None = None,
    p_features: set[str] | None = None,
) -> list[list[object]]:
    try:
        import pywrapfst as fst
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise typer.BadParameter(
            "Pynini/pywrapfst not available; install pynini to use --pynini."
        ) from exc

    machine = compile_pynini_fst(
        rule, v_features=v_features, p_features=p_features
    )
    v_order = machine.v_order
    if set(v_order) != set(feature_order):
        raise typer.BadParameter(
            "Alphabet features do not match Pynini features: "
            f"alphabet={sorted(feature_order)}; pynini={sorted(v_order)}"
        )
    fst_machine = machine.fst

    output_words: list[list[object]] = []
    for idx, word in enumerate(words):
        if not isinstance(word, list):
            raise typer.BadParameter(
                f"Word at index {idx} is not an array of symbols."
            )
        word_symbols = word[::-1] if rule.dir == "RIGHT" else word
        input_labels: list[int] = []
        for sym in word_symbols:
            if not isinstance(sym, str) or not sym.strip():
                raise typer.BadParameter(
                    f"Word {idx} contains a non-string symbol."
                )
            if sym not in symbol_to_bundle:
                raise typer.BadParameter(
                    f"Word {idx} has unknown symbol: {sym!r}"
                )
            bundle = symbol_to_bundle[sym]
            input_labels.append(
                _encode_tv_label(_bundle_to_tv_tuple(bundle, v_order))
            )

        input_fst = _pynini_linear_fst(input_labels, fst)
        composed = fst.compose(input_fst, fst_machine)
        output_fst = fst.shortestpath(composed)
        output_labels = _pynini_output_labels(output_fst)
        output_syms = _labels_to_alphabet(
            output_labels,
            v_order,
            feature_order,
            bundle_to_symbol,
            strict,
        )
        if rule.dir == "RIGHT":
            output_syms = list(reversed(output_syms))
        output_words.append(output_syms)
    return output_words


def _pynini_fst_from_machine(machine, fst) -> "fst.Fst":
    max_state = machine.start_state
    for src, _, _, dst in machine.arcs:
        if src > max_state:
            max_state = src
        if dst > max_state:
            max_state = dst
    if machine.final_states:
        max_state = max(max_state, max(machine.final_states))

    fst_machine = fst.VectorFst()
    for _ in range(max_state + 1):
        fst_machine.add_state()
    fst_machine.set_start(machine.start_state)
    weight = fst.Weight.one(fst_machine.weight_type())
    for state in machine.final_states:
        fst_machine.set_final(state, weight)
    for src, ilabel, olabel, dst in machine.arcs:
        fst_machine.add_arc(
            src, fst.Arc(ilabel, olabel, weight, dst)
        )
    return fst_machine


def _pynini_linear_fst(labels: list[int], fst) -> "fst.Fst":
    f = fst.VectorFst()
    start = f.add_state()
    f.set_start(start)
    weight = fst.Weight.one(f.weight_type())
    state = start
    for label in labels:
        next_state = f.add_state()
        f.add_arc(state, fst.Arc(label, label, weight, next_state))
        state = next_state
    f.set_final(state, weight)
    return f


def _pynini_output_labels(fst_obj: "fst.Fst") -> list[int]:
    start = fst_obj.start()
    if start == -1:
        raise typer.BadParameter("No path found in Pynini output.")
    labels: list[int] = []
    state = start
    while True:
        arcs = list(fst_obj.arcs(state))
        if not arcs:
            break
        if len(arcs) > 1:
            raise typer.BadParameter(
                "Non-deterministic output path in Pynini output."
            )
        arc = arcs[0]
        if arc.olabel != 0:
            labels.append(arc.olabel)
        state = arc.nextstate
    return labels


def _encode_tv_label(bundle: tuple[int, ...]) -> int:
    label = 1
    base = 1
    for value in bundle:
        label += value * base
        base *= 3
    return label


def _decode_tv_label(label: int, size: int) -> tuple[int, ...]:
    if label <= 0:
        raise typer.BadParameter(f"Invalid label: {label}")
    value = label - 1
    digits: list[int] = []
    for _ in range(size):
        digits.append(value % 3)
        value //= 3
    return tuple(digits)


def _labels_to_alphabet(
    labels: list[int],
    v_order: tuple[str, ...],
    feature_order: tuple[str, ...],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
) -> list[object]:
    output: list[object] = []
    for label in labels:
        bundle = _tv_tuple_to_bundle(_decode_tv_label(label, len(v_order)), v_order)
        bundle_key = tuple(bundle.get(feature, "0") for feature in feature_order)
        if bundle_key not in bundle_to_symbol:
            if strict:
                raise typer.BadParameter(
                    f"Output bundle has no symbol: {bundle_key}"
                )
            output.append(bundle)
        else:
            output.append(bundle_to_symbol[bundle_key])
    return output


def _bundle_to_tv_tuple(
    bundle: dict[str, str], v_order: tuple[str, ...]
) -> tuple[int, ...]:
    values: list[int] = []
    for feature in v_order:
        value = bundle.get(feature, "0")
        if value == "+":
            values.append(1)
        elif value == "-":
            values.append(2)
        else:
            values.append(0)
    return tuple(values)


def _tv_tuple_to_bundle(
    bundle: tuple[int, ...], v_order: tuple[str, ...]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for feature, value in zip(v_order, bundle):
        if value == 1:
            result[feature] = "+"
        elif value == 2:
            result[feature] = "-"
    return result


def _enumerate_sigma(size: int) -> list[BundleTuple]:
    values: Sequence[int] = (0, 1, 2)
    if size <= 0:
        return [tuple()]
    bundles: list[BundleTuple] = [tuple()]
    for _ in range(size):
        bundles = [bundle + (value,) for bundle in bundles for value in values]
    return bundles


def _encode_label(bundle: BundleTuple) -> int:
    label = 1
    base = 1
    for value in bundle:
        label += value * base
        base *= 3
    return label


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


def _write_symtab(machine: PyniniMachine, path: Path) -> None:
    lines = ["<eps> 0"]
    for bundle in _enumerate_sigma(len(machine.v_order)):
        label = _encode_label(bundle)
        symbol = _symbol_for_bundle(bundle, machine.v_order)
        lines.append(f"{symbol} {label}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
