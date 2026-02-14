import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app  # noqa: E402


def test_eval_cli_outputs_json(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(bundle (- Voice))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )

    input_segments = [
        ["a", "b", "c"],
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_segments), encoding="utf-8")

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(rules_path),
            str(alphabet_path),
            str(input_path),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output == {
        "id": "rules",
        "inputs": [["a", "b", "c"]],
        "rows": [
            {
                "rule_id": "spread_voice_right",
                "outputs": [["d", "b", "c"]],
            }
        ],
    }


def test_eval_cli_non_strict_emits_bundle(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(
        ",a,b,c\nVoice,+,-,0\nConsonantal,0,+,-\n",
        encoding="utf-8",
    )

    input_segments = [
        ["a", "b", "c"],
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_segments), encoding="utf-8")

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(rules_path),
            str(alphabet_path),
            str(input_path),
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output == {
        "id": "rules",
        "inputs": [["a", "b", "c"]],
        "rows": [
            {
                "rule_id": "spread_voice_right",
                "outputs": [[{"Voice": "-"}, "b", "c"]],
            }
        ],
    }


def test_eval_cli_pynini_compare_right_rule(tmp_path: Path) -> None:
    pytest.importorskip("pywrapfst")
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )

    input_segments = [
        ["a", "b", "c", "a"],
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_segments), encoding="utf-8")

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(rules_path),
            str(alphabet_path),
            str(input_path),
            "--output",
            str(output_path),
            "--compare",
        ],
    )
    assert result.exit_code == 0, result.output


def test_eval_cli_dump_vp(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )

    input_segments = [
        ["a", "b", "c", "a"],
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_segments), encoding="utf-8")

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(rules_path),
            str(alphabet_path),
            str(input_path),
            "--output",
            str(output_path),
            "--dump-vp",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "V:" in result.output
    assert "P:" in result.output
