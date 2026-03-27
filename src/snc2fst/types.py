from typing import Literal, TypeAlias

Feature: TypeAlias = str
Valence: TypeAlias = Literal["+", "-", "0"]
ValuedFeature: TypeAlias = tuple[Valence, Feature]
Segment: TypeAlias = dict[Feature, Valence]
FeatureSpec: TypeAlias = list[ValuedFeature]
FeatureSpecSequence: TypeAlias = list[FeatureSpec]
Word: TypeAlias = list[Segment]
