import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


@pytest.mark.smoke
def test_cli_smoke(tmp_path: Path) -> None:
    pytest.importorskip("pywrapfst")
    runner = CliRunner()

    # init
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output

    alphabet = tmp_path / "alphabet.csv"
    rules = tmp_path / "rules.toml"
    inputs = tmp_path / "input.toml"
    assert alphabet.exists()
    assert rules.exists()
    assert inputs.exists()

    # validate
    result = runner.invoke(
        app, ["validate", str(rules), "--alphabet", str(alphabet)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "validate",
            str(inputs),
            "--kind",
            "input",
            "--alphabet",
            str(alphabet),
        ],
    )
    assert result.exit_code == 0, result.output

    # compile
    att_path = tmp_path / "rule.att"
    result = runner.invoke(
        app, ["compile", str(rules), str(att_path), "--alphabet", str(alphabet)]
    )
    assert result.exit_code == 0, result.output
    assert att_path.exists()
    assert att_path.read_text(encoding="utf-8").strip()

    # eval with compare
    out_path = tmp_path / "out.json"
    result = runner.invoke(
        app,
        [
            "eval",
            str(rules),
            str(inputs),
            "--output",
            str(out_path),
            "--alphabet",
            str(alphabet),
            "--pynini",
            "--compare",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("id") == "sample_rules"
    assert "inputs" in payload
    assert "rows" in payload
    assert payload["rows"]
