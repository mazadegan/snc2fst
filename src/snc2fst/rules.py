from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Direction = Literal["LEFT", "RIGHT"]
Polarity = Literal["+", "-"]


class Rule(BaseModel):
    id: str
    dir: Direction
    inr: list[tuple[Polarity, str]] = Field(default_factory=list)
    trm: list[tuple[Polarity, str]] = Field(default_factory=list)
    cnd: list[tuple[Polarity, str]] = Field(default_factory=list)
    out: str

    @model_validator(mode="after")
    def _validate_shape(self) -> "Rule":
        if not self.id.strip():
            raise ValueError("Rule id cannot be empty.")
        if not self.out.strip():
            raise ValueError("Rule out expression cannot be empty.")
        for label, cls in (("inr", self.inr), ("trm", self.trm), ("cnd", self.cnd)):
            for polarity, feature in cls:
                if not feature.strip():
                    raise ValueError(f"Rule {label} has empty feature name.")
        return self


class RulesFile(BaseModel):
    id: str
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rules(self) -> "RulesFile":
        if not self.id.strip():
            raise ValueError("Rules file id cannot be empty.")
        ids = [rule.id for rule in self.rules]
        seen: set[str] = set()
        dupes: list[str] = []
        for rule_id in ids:
            if rule_id in seen and rule_id not in dupes:
                dupes.append(rule_id)
            seen.add(rule_id)
        if dupes:
            raise ValueError(f"Duplicate rule ids: {', '.join(dupes)}")
        return self
