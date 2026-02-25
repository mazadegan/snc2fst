import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app  # noqa: E402


def test_eval_directory_mode_uses_project_config(tmp_path: Path) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "rules"\n\n[[rules]]\n'
        'id = "spread_voice_right"\n'
        'dir = "RIGHT"\n'
        'inr = [["+", "Voice"]]\n'
        'trm = [["+", "Consonantal"]]\n'
        "cnd = []\n"
        'out = "(bundle (- Voice))"\n',
        encoding="utf-8",
    )
    (tmp_path / "alphabet.csv").write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["a","b","c"]]\n',
        encoding="utf-8",
    )
    (tmp_path / "snc2fst.toml").write_text(
        "[paths]\n"
        'alphabet = "alphabet.csv"\n'
        'rules = "rules.toml"\n'
        'input = "input.toml"\n',
        encoding="utf-8",
    )

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(tmp_path), "--output", str(output_path)],
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


def test_eval_directory_mode_partial_overrides_error(tmp_path: Path) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "rules"\n\n[[rules]]\n'
        'id = "r"\n'
        'dir = "LEFT"\n'
        "inr = []\n"
        "trm = []\n"
        "cnd = []\n"
        'out = "(proj INR *)"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(tmp_path),
            "--rules",
            str(tmp_path / "rules.toml"),
        ],
    )
    assert result.exit_code != 0
    assert "partial explicit overrides" in result.output


def test_eval_directory_mode_missing_configured_rules_path_is_concise(
    tmp_path: Path,
) -> None:
    (tmp_path / "alphabet.csv").write_text(
        ",a,b\nVoice,+,-\n",
        encoding="utf-8",
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["a"]]\n',
        encoding="utf-8",
    )
    (tmp_path / "snc2fst.toml").write_text(
        "[paths]\n"
        'alphabet = "alphabet.csv"\n'
        'rules = "rules2.toml"\n'
        'input = "input.toml"\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["eval", str(tmp_path)])
    assert result.exit_code != 0
    assert "Configured snc2fst.toml [paths].rules not found" in result.output
    assert "pass --rules <path>" in result.output


def test_eval_directory_mode_invalid_configured_rules_schema_is_concise(
    tmp_path: Path,
) -> None:
    (tmp_path / "alphabet.csv").write_text(
        ",a,b\nVoice,+,-\n",
        encoding="utf-8",
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["a"]]\n',
        encoding="utf-8",
    )
    (tmp_path / "out.json").write_text(
        '{"id":"sample_rules","inputs":[["a"]],"rows":[{"rule_id":"r","outputs":[["a"]]}]}',
        encoding="utf-8",
    )
    (tmp_path / "snc2fst.toml").write_text(
        "[paths]\n"
        'alphabet = "alphabet.csv"\n'
        'rules = "out.json"\n'
        'input = "input.toml"\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["eval", str(tmp_path)])
    assert result.exit_code != 0
    assert "Configured snc2fst.toml [paths].rules is invalid" in result.output
    assert "--rules" in result.output
    assert "<path>" in result.output


def test_eval_directory_mode_ambiguous_rules_errors(
    tmp_path: Path,
) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "primary_rules"\n\n[[rules]]\n'
        'id = "spread_voice_right"\n'
        'dir = "RIGHT"\n'
        'inr = [["+", "Voice"]]\n'
        'trm = [["+", "Consonantal"]]\n'
        "cnd = []\n"
        'out = "(bundle (- Voice))"\n',
        encoding="utf-8",
    )
    (tmp_path / "other_rules.toml").write_text(
        'id = "secondary_rules"\n\n[[rules]]\n'
        'id = "identity"\n'
        'dir = "LEFT"\n'
        "inr = []\n"
        "trm = []\n"
        "cnd = []\n"
        'out = "(proj INR *)"\n',
        encoding="utf-8",
    )
    (tmp_path / "alphabet.csv").write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["a","b","c"]]\n',
        encoding="utf-8",
    )

    output_path = tmp_path / "output.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(tmp_path), "--output", str(output_path)],
    )
    assert result.exit_code != 0
    assert "Found multiple rules files" in result.output


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
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--input",
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
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--input",
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
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--input",
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
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--dump-vp",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "V:" in result.output
    assert "P:" in result.output


def test_eval_cli_outputs_tex(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "R_1",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(bundle (- Voice))",
            }
        ],
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(
        ",a,b,c,d\nVoice,+,-,0,-\nConsonantal,0,+,-,0\n",
        encoding="utf-8",
    )

    input_segments = [["a", "b"], ["b", "c"]]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_segments), encoding="utf-8")

    output_path = tmp_path / "output.tex"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--input",
            str(input_path),
            "--format",
            "tex",
            "--output",
            str(output_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == (
        "\\begin{tabular}{rcc}\n"
        "  UR & /ab/ & /bc/ \\\\\n"
        "  \\hline\n"
        "  $R_1$ & [db] & --- \\\\\n"
        "  SR & [db] & [bc] \\\\\n"
        "\\end{tabular}\n"
    )
