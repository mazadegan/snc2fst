from pydantic import BaseModel, field_validator
from typing import Literal

class Rule(BaseModel):
    Id: str
    Inr: list[str] 
    Trm: list[str]
    Dir: Literal["L", "R"] 
    Out: str

    @field_validator('Inr', 'Trm')
    @classmethod
    def parse_natural_classes(cls, v: list[str]) -> list[list[tuple[str, str]]]:
        """
        Converts ['+Syllabic', '-Sonorant'] into [('+', 'Syllabic'), ('-', 'Sonorant')]
        """
        parsed_classes = []
        for feature_string in v:
            sign = feature_string[0]
            feature = feature_string[1:]
            parsed_classes.append([(sign, feature)])
        return parsed_classes

class GrammarConfig(BaseModel):
    alphabet_path: str
    tests_path: str
    rules: list[Rule]