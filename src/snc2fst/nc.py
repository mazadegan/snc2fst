"""Natural class helpers shared by the CLI and web UI."""

from __future__ import annotations

import re


def split_segments(raw: str) -> list[str]:
    parts = [piece.strip() for piece in re.split(r"[\s,]+", raw.strip()) if piece.strip()]
    if not parts:
        raise ValueError("No segments were provided.")
    return parts


def parse_bundle(raw: str) -> list[tuple[str, str]]:
    tokens = [piece.strip() for piece in re.split(r"[\s,]+", raw.strip()) if piece.strip()]
    bundle: list[tuple[str, str]] = []
    for token in tokens:
        if len(token) < 2 or token[0] not in "+-":
            raise ValueError(
                f"Invalid valued feature '{token}'. Use forms like '+syll' or '-high'."
            )
        bundle.append((token[0], token[1:]))
    return bundle


def bundle_str(bundle: list[tuple[str, str]]) -> str:
    if not bundle:
        return "{}"
    return "{" + " ".join(f"{sign}{feature}" for sign, feature in bundle) + "}"


def matching_segments(
    alphabet: dict[str, dict[str, str]],
    bundle: list[tuple[str, str]],
) -> list[str]:
    matches: list[str] = []
    for segment, features in alphabet.items():
        if all(features.get(feature) == sign for sign, feature in bundle):
            matches.append(segment)
    return matches


def shared_valued_features(
    alphabet: dict[str, dict[str, str]],
    segments: list[str],
) -> list[tuple[str, str]]:
    if not segments:
        return []

    shared: list[tuple[str, str]] = []
    feature_names = sorted({feature for bundle in alphabet.values() for feature in bundle})
    for feature in feature_names:
        first = alphabet[segments[0]].get(feature)
        if first not in ("+", "-"):
            continue
        if all(alphabet[segment].get(feature) == first for segment in segments[1:]):
            shared.append((first, feature))
    return shared


def inspect_segments(
    alphabet: dict[str, dict[str, str]],
    segments: list[str],
) -> dict[str, object]:
    bundle = shared_valued_features(alphabet, segments)
    matches = matching_segments(alphabet, bundle)
    target_set = set(segments)
    extras = [segment for segment in matches if segment not in target_set]
    return {
        "segments": segments,
        "bundle": bundle,
        "matches": matches,
        "extras": extras,
        "is_exact": not extras and set(matches) == target_set,
    }
