import json
import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_validate_rules_json(tmp_path: Path) -> None:
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
    result = runner.invoke(app, ["validate", str(rules_path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"
