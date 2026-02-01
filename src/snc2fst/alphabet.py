from __future__ import annotations

from typing import Dict, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FeatureValue = Literal["+", "-", "0"]


class FeatureSchema(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)


class SymbolFeatures(BaseModel):
    symbol: str
    features: Dict[str, FeatureValue]


class Alphabet(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    feature_schema: FeatureSchema = Field(alias="schema")
    rows: list[SymbolFeatures]

    @model_validator(mode="after")
    def _validate_consistency(self) -> "Alphabet":
        symbols = self.feature_schema.symbols
        features = self.feature_schema.features

        if not symbols:
            raise ValueError("Schema must contain at least one symbol.")
        if not features:
            raise ValueError("Schema must contain at least one feature.")

        dupes = _find_dupes(symbols)
        if dupes:
            raise ValueError(f"Duplicate symbols: {', '.join(dupes)}")

        dupes = _find_dupes(features)
        if dupes:
            raise ValueError(f"Duplicate features: {', '.join(dupes)}")

        row_symbols = [row.symbol for row in self.rows]
        dupes = _find_dupes(row_symbols)
        if dupes:
            raise ValueError(f"Duplicate row symbols: {', '.join(dupes)}")

        if set(row_symbols) != set(symbols):
            missing = [sym for sym in symbols if sym not in row_symbols]
            extra = [sym for sym in row_symbols if sym not in symbols]
            if missing:
                raise ValueError(f"Rows missing symbols: {', '.join(missing)}")
            if extra:
                raise ValueError(f"Rows contain unknown symbols: {', '.join(extra)}")

        feature_set = set(features)
        for row in self.rows:
            if set(row.features.keys()) != feature_set:
                missing = [f for f in features if f not in row.features]
                extra = [f for f in row.features if f not in feature_set]
                if missing:
                    raise ValueError(
                        f"Symbol {row.symbol!r} missing features: {', '.join(missing)}"
                    )
                if extra:
                    raise ValueError(
                        f"Symbol {row.symbol!r} has unknown features: {', '.join(extra)}"
                    )

        return self

    @classmethod
    def from_matrix(
        cls,
        symbols: list[str],
        features: list[str],
        values: list[list[FeatureValue]],
    ) -> "Alphabet":
        if len(values) != len(features):
            raise ValueError("Feature/value row count does not match features length.")
        rows = []
        for idx, symbol in enumerate(symbols):
            bundle = {feature: values[f_idx][idx] for f_idx, feature in enumerate(features)}
            rows.append(SymbolFeatures(symbol=symbol, features=bundle))
        return cls(feature_schema=FeatureSchema(symbols=symbols, features=features), rows=rows)


def _find_dupes(items: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for item in items:
        if item in seen and item not in dupes:
            dupes.append(item)
        seen.add(item)
    return dupes


def format_validation_error(error: ValidationError) -> str:
    parts: list[str] = []
    for err in error.errors():
        loc = ".".join(str(part) for part in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        if loc:
            parts.append(f"{loc}: {msg}")
        else:
            parts.append(msg)
    return "; ".join(parts)
