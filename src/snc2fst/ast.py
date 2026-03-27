from __future__ import annotations
from dataclasses import dataclass
from typing import TypeAlias, Union

# ---------------------------------------------------------------------------
# Feature data nodes
# ---------------------------------------------------------------------------


@dataclass
class ValuedFeature:
    sign: str  # '+' or '-'
    name: str


@dataclass
class FeatureSpec:
    features: list[ValuedFeature]


@dataclass
class FeatureNames:
    names: list[str]


@dataclass
class NcSequence:
    specs: list[FeatureSpec]


# ---------------------------------------------------------------------------
# Leaf nodes
# ---------------------------------------------------------------------------


@dataclass
class Inr:
    pass


@dataclass
class Trm:
    pass


@dataclass
class Integer:
    value: int


@dataclass
class Symbol:
    name: str  # alphabet segment name, e.g. 'A -> name='A'


# ---------------------------------------------------------------------------
# Operation nodes
# ---------------------------------------------------------------------------


@dataclass
class Nth:
    index: Integer
    sequence: Expr


@dataclass
class InClass:
    segment: Expr
    spec: FeatureSpec


@dataclass
class Models:
    sequence: Expr
    nc_seq: NcSequence


@dataclass
class If:
    cond: Expr
    then: Expr
    else_: Expr


@dataclass
class Unify:
    segment: Expr
    features: FeatureSpec


@dataclass
class Subtract:
    segment: Expr
    features: FeatureSpec


@dataclass
class Project:
    segment: Expr
    names: FeatureNames


@dataclass
class Concat:
    args: list[Expr]


# ---------------------------------------------------------------------------
# Union of all AST node types
# ---------------------------------------------------------------------------

Expr: TypeAlias = Union[
    Inr,
    Trm,
    Integer,
    Symbol,
    Nth,
    InClass,
    Models,
    If,
    Unify,
    Subtract,
    Project,
    Concat,
    FeatureSpec,
    FeatureNames,
    NcSequence,
]
