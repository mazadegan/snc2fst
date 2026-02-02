import json
import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_compile_writes_att_and_symtab(tmp_path: Path) -> None:
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

    output_path = tmp_path / "tv.att"
    runner = CliRunner()
    result = runner.invoke(app, ["compile", str(rules_path), str(output_path)])
    assert result.exit_code == 0, result.output

    symtab_path = output_path.with_suffix(".sym")
    assert output_path.exists()
    assert symtab_path.exists()
    assert output_path.read_text(encoding="utf-8").strip()
    assert symtab_path.read_text(encoding="utf-8").strip()


def test_compile_respects_max_arcs(tmp_path: Path) -> None:
    rules = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    output_path = tmp_path / "tv.att"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["compile", str(rules_path), str(output_path), "--max-arcs", "1"],
    )
    assert result.exit_code != 0
    assert "--max-arcs" in result.output
