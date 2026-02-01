import json
import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_validate_rules_json(tmp_path: Path) -> None:
    alphabet = {
        "schema": {"symbols": ["a"], "features": ["Voice", "Consonantal"]},
        "rows": [
            {"symbol": "a", "features": {"Voice": "0", "Consonantal": "0"}}
        ],
    }
    alphabet_path = tmp_path / "alphabet.json"
    alphabet_path.write_text(json.dumps(alphabet), encoding="utf-8")

    rules = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(unify (subtract TRM (proj TRM (Voice))) (proj INR (Voice)))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app, ["validate", str(rules_path), "--alphabet", str(alphabet_path)]
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"


def test_validate_rules_unknown_out_feature(tmp_path: Path) -> None:
    alphabet = {
        "schema": {"symbols": ["a"], "features": ["Voice"]},
        "rows": [{"symbol": "a", "features": {"Voice": "0"}}],
    }
    alphabet_path = tmp_path / "alphabet.json"
    alphabet_path.write_text(json.dumps(alphabet), encoding="utf-8")

    rules = {
        "rules": [
            {
                "id": "bad_out",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [],
                "cnd": [],
                "out": "(lit + Continuant)",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app, ["validate", str(rules_path), "--alphabet", str(alphabet_path)]
    )
    assert result.exit_code != 0
    assert "unknown feature" in result.output.lower()
