import re
from pathlib import Path
from typing import Literal

import logical_phonology as lp
from pydantic import BaseModel, field_validator

from snc2fst.errors import RuleError

FEATURE_PATTERN = re.compile(r"^([+\-])(\w+)$")


class Meta(BaseModel):
    title: str
    language: str  # ISO 639-3 preferred; 639-2 or names accepted at load time
    path_to_readme: Path
    sources: list[str] = []
    compilable: bool = True


class Rule(BaseModel):
    Id: str
    Inr: list[list[tuple[str, str]]]
    Trm: list[list[tuple[str, str]]]
    Dir: Literal["L", "R"]
    Out: str

    def inr_as_ncs(self, fs: lp.FeatureSystem) -> lp.NaturalClassSequence:
        """Return the Inr specification as an LP NaturalClassSequence."""
        return self._as_ncs(self.Inr, fs)

    def trm_as_ncs(self, fs: lp.FeatureSystem) -> lp.NaturalClassSequence:
        """Return the Trm specification as an LP NaturalClassSequence."""
        return self._as_ncs(self.Trm, fs)

    def _as_ncs(
        self, sequence: list[list[tuple[str, str]]], fs: lp.FeatureSystem
    ) -> lp.NaturalClassSequence:
        """Convert a parsed Inr or Trm specification into an LP
        NaturalClassSequence.

        Raises:
            RuleError: If any feature name is not in the feature system.
        """
        try:
            return fs.natural_class_sequence(
                [
                    fs.natural_class(
                        {
                            feature: lp.FeatureValue.from_str(value)
                            for value, feature in nc_spec
                        }
                    )
                    for nc_spec in sequence
                ]
            )
        except lp.UnknownFeatureError as e:
            raise RuleError(
                f"Rule '{self.Id}': unknown feature(s) {e.unknown}."
            ) from e

    @field_validator("Id")
    @classmethod
    def validate_rule_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Rule Id must not be empty.")
        if not re.match(r"^[\w\-]+$", v):
            raise ValueError(
                f"Rule Id '{v}' is not a valid identifier. "
                "Use only letters, numbers, underscores, and hyphens."
            )
        return v.strip()

    @field_validator("Inr", "Trm", mode="before")
    @classmethod
    def parse_natural_class_sequences(
        cls, v: list[list[str]]
    ) -> list[list[tuple[str, str]]]:
        """
        Validates and converts [['+F1'], ['+F1', '-F2']]
        into [[('+', 'F1')], [('+', 'F1'), ('-', 'F2')]]
        """
        sequence: list[list[tuple[str, str]]] = []
        for natural_class_specification in v:
            specification: list[tuple[str, str]] = []
            for valued_feature_str in natural_class_specification:
                match = FEATURE_PATTERN.match(valued_feature_str.strip())
                if not match:
                    raise ValueError(
                        f"Invalid feature syntax: '{valued_feature_str}'. "
                        f"Features must begin with '+' or '-', followed by the feature name. "  # noqa: E501
                        f"(Expected pattern: {FEATURE_PATTERN.pattern})"
                    )
                sign, feature_name = match.groups()
                specification.append((sign, feature_name))
            sequence.append(specification)
        return sequence


class GrammarConfig(BaseModel):
    meta: Meta
    alphabet_path: str
    tests_path: Path
    rules: list[Rule]
