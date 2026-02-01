import json
import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_eval_cli_outputs_json(tmp_path: Path) -> None:
    rules = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(lit - Voice)",
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
            str(input_path),
            str(output_path),
            "--alphabet",
            str(alphabet_path),
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output == [["d", "b", "c"]]


def test_eval_cli_non_strict_emits_bundle(tmp_path: Path) -> None:
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
            str(input_path),
            str(output_path),
            "--alphabet",
            str(alphabet_path),
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output == [[{"Voice": "-"}, "b", "c"]]


def test_eval_cli_compare_requires_backend(tmp_path: Path) -> None:
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
            str(input_path),
            str(output_path),
            "--alphabet",
            str(alphabet_path),
            "--compare",
        ],
    )
    assert result.exit_code != 0
    assert "--fst" in result.output or "--tv" in result.output


def test_eval_cli_tv_compare_right_rule(tmp_path: Path) -> None:
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
            str(input_path),
            str(output_path),
            "--alphabet",
            str(alphabet_path),
            "--tv",
            "--compare",
        ],
    )
    assert result.exit_code == 0, result.output
