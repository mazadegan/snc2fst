import re
from pydantic import BaseModel, field_validator, model_validator
from typing import Literal
from snc2fst.types import FeatureSpecSequence

FEATURE_PATTERN = re.compile(r'^([+\-])(\w+)$')


class Meta(BaseModel):
    title: str
    language: str          # ISO 639-3 preferred; 639-2 or names accepted at load time
    description: str = ""
    sources: list[str] = []
    compilable: bool = True

class Rule(BaseModel):
    Id: str
    Inr: list[list[str]] 
    Trm: list[list[str]]
    Dir: Literal["L", "R"] 
    Out: str

    @field_validator('Inr', 'Trm')
    @classmethod
    def parse_natural_classes(cls, v: list[list[str]]) -> FeatureSpecSequence:
        """
        Validates and converts [['+F1'], ['+F1', '-F2']] 
        into [[('+', 'F1')], [('+', 'F1'), ('-', 'F2')]]
        """
        parsed_sequence = []
        for feature_spec in v:
            parsed_class = []
            for feature_str in feature_spec:
                match = FEATURE_PATTERN.match(feature_str.strip())
                if not match:
                    raise ValueError(
                        f"Invalid feature syntax: '{feature_str}'. "
                        f"Features must begin with '+' or '-', followed by the feature name. "
                        f"(Expected pattern: {FEATURE_PATTERN.pattern})"
                    )
                sign, feature_name = match.groups()
                parsed_class.append((sign, feature_name))
            parsed_sequence.append(parsed_class)
        return parsed_sequence

class GrammarConfig(BaseModel):
    meta: Meta
    alphabet_path: str
    tests_path: str
    rules: list[Rule]