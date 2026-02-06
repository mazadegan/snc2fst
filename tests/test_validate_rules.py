import json
import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_validate_rules_json(tmp_path: Path) -> None:
    alphabet_content = ",a\nVoice,0\nConsonantal,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

    rules = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(unify (subtract (proj TRM *) (proj TRM (Voice))) (proj INR (Voice)))",
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


def test_validate_input_words(tmp_path: Path) -> None:
    alphabet_content = ",a,b\nVoice,0,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

    payload = [["a", "b"], ["b"]]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(input_path),
            "--kind",
            "input",
            "--alphabet",
            str(alphabet_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"


def test_validate_input_words_auto_detect(tmp_path: Path) -> None:
    alphabet_content = ",a,b\nVoice,0,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

    payload = [["a", "b"], ["b"]]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(input_path),
            "--alphabet",
            str(alphabet_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"


def test_validate_rules_dump_vp(tmp_path: Path) -> None:
    alphabet_content = ",a\nVoice,0\nConsonantal,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

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

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--dump-vp",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "spread_voice_right V:" in result.output
    assert "spread_voice_right P:" in result.output


def test_validate_rules_fst_stats(tmp_path: Path) -> None:
    alphabet_content = ",a\nVoice,0\nConsonantal,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

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

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--fst-stats",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "spread_voice_right states: 4 arcs: 36" in result.output


def test_validate_rules_unknown_out_feature(tmp_path: Path) -> None:
    alphabet_content = ",a\nVoice,0\n"
    alphabet_path = tmp_path / "alphabet.csv"
    alphabet_path.write_text(alphabet_content, encoding="utf-8")

    rules = {
        "rules": [
            {
                "id": "bad_out",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [],
                "cnd": [],
                "out": "(bundle (+ Continuant))",
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
