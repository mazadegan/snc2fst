from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias, Union

### Feature Data Nodes ###


@dataclass(frozen=True)
class ValuedFeature:
    name: str
    sign: Literal["+", "-"]


@dataclass(frozen=True)
class FeatureSpec:
    features: tuple[ValuedFeature, ...]


@dataclass(frozen=True)
class FeatureNames:
    names: tuple[str, ...]


@dataclass(frozen=True)
class NcSequence:
    specs: tuple[FeatureSpec, ...]


### Leaf Nodes ###


@dataclass(frozen=True)
class Inr:
    pass


@dataclass(frozen=True)
class Trm:
    pass


@dataclass(frozen=True)
class Symbol:
    name: str  # segment's name in the alphabet


### Operation Nodes ###


@dataclass(frozen=True)
class Slice:
    start: int
    end: int
    sequence: Inr | Trm


@dataclass(frozen=True)
class InClass:
    sequence: Expr
    nc_sequence: NcSequence


@dataclass(frozen=True)
class If:
    cond: Expr
    then: Expr
    else_: Expr


@dataclass(frozen=True)
class Unify:
    segment: Expr
    features: Expr  # FeatureSpec literal or any segment-returning expression


@dataclass(frozen=True)
class Subtract:
    segment: Expr
    features: FeatureSpec


@dataclass(frozen=True)
class Project:
    segment: Expr
    names: FeatureNames


@dataclass(frozen=True)
class Concat:
    args: tuple[Expr, ...]


Expr: TypeAlias = Union[
    Inr,
    Trm,
    Symbol,
    Slice,
    InClass,
    If,
    Unify,
    Subtract,
    Project,
    Concat,
    FeatureSpec,
    FeatureNames,
    NcSequence,
]
