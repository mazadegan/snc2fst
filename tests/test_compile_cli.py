import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app  # noqa: E402

pytest.importorskip("pywrapfst")


def _write_alphabet_csv(
    path: Path, *, symbols: list[str], features: list[str]
) -> None:
    lines = ["," + ",".join(symbols)]
    for feature in features:
        values = ["+" if idx % 2 == 0 else "-" for idx in range(len(symbols))]
        lines.append(",".join([feature] + values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_compile_writes_att_and_symtab(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+", "Voice"]],
                "trm": [["+", "Consonantal"]],
                "cnd": [],
                "out": "(unify (subtract (proj TRM *) (proj TRM (Voice))) (proj INR (Voice)))",
            }
        ],
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    alphabet_path = tmp_path / "alphabet.csv"
    _write_alphabet_csv(
        alphabet_path,
        symbols=["A", "B"],
        features=["Voice", "Consonantal"],
    )

    output_dir = tmp_path / "compiled"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compile",
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--output",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    output_path = output_dir / "spread_voice_right.att"
    symtab_path = output_dir / "spread_voice_right.sym"
    assert output_dir.exists()
    assert output_path.exists()
    assert symtab_path.exists()
    assert output_path.read_text(encoding="utf-8").strip()
    assert symtab_path.read_text(encoding="utf-8").strip()


def test_compile_outputs_expected_att_and_symtab(tmp_path: Path) -> None:
    rules = {
        "id": "rules",
        "rules": [
            {
                "id": "identity_left",
                "dir": "LEFT",
                "inr": [],
                "trm": [],
                "cnd": [],
                "out": "(proj INR *)",
            }
        ],
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    alphabet_path = tmp_path / "alphabet.csv"
    _write_alphabet_csv(
        alphabet_path,
        symbols=["A", "B"],
        features=["Voice"],
    )

    output_dir = tmp_path / "compiled"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compile",
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--output",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    output_path = output_dir / "identity_left.att"
    symtab_path = output_dir / "identity_left.sym"
    assert output_path.exists()
    assert symtab_path.exists()

    expected_att = "\n".join(
        [
            "0 1 1 1 0",
            "0 1 2 2 0",
            "0 1 3 3 0",
            "1 1 1 1 0",
            "1 1 2 2 0",
            "1 1 3 3 0",
            "0 0",
            "1 0",
            "",
        ]
    )
    expected_symtab = "\n".join(
        [
            "<eps> 0",
            "Voice0 1",
            "Voice+ 2",
            "Voice- 3",
            "",
        ]
    )
    assert output_path.read_text(encoding="utf-8") == expected_att
    assert symtab_path.read_text(encoding="utf-8") == expected_symtab


def test_compile_respects_max_arcs(tmp_path: Path) -> None:
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
        ],
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    alphabet_path = tmp_path / "alphabet.csv"
    _write_alphabet_csv(
        alphabet_path,
        symbols=["A", "B"],
        features=["Voice", "Consonantal"],
    )

    output_dir = tmp_path / "compiled"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compile",
            str(tmp_path),
            "--rules",
            str(rules_path),
            "--alphabet",
            str(alphabet_path),
            "--output",
            str(output_dir),
            "--max-arcs",
            "1",
        ],
    )
    assert result.exit_code != 0
    assert "--max-arcs" in result.output


def test_compile_directory_mode_uses_project_config(tmp_path: Path) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "rules"\n\n[[rules]]\n'
        'id = "identity_left"\n'
        'dir = "LEFT"\n'
        "inr = []\n"
        "trm = []\n"
        "cnd = []\n"
        'out = "(proj INR *)"\n',
        encoding="utf-8",
    )
    _write_alphabet_csv(
        tmp_path / "alphabet.csv",
        symbols=["A", "B"],
        features=["Voice"],
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["A"]]\n',
        encoding="utf-8",
    )
    (tmp_path / "snc2fst.toml").write_text(
        "[paths]\n"
        'alphabet = "alphabet.csv"\n'
        'rules = "rules.toml"\n'
        'input = "input.toml"\n',
        encoding="utf-8",
    )

    output_dir = tmp_path / "compiled"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compile",
            str(tmp_path),
            "--output",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (output_dir / "identity_left.att").exists()
    assert (output_dir / "identity_left.sym").exists()


def test_compile_directory_mode_partial_overrides_error(tmp_path: Path) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "rules"\n\n[[rules]]\n'
        'id = "identity_left"\n'
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
            "compile",
            str(tmp_path),
            "--rules",
            str(tmp_path / "rules.toml"),
        ],
    )
    assert result.exit_code != 0
    assert "partial explicit overrides" in result.output


def test_compile_directory_mode_defaults_to_compiled_dir(tmp_path: Path) -> None:
    (tmp_path / "rules.toml").write_text(
        'id = "rules"\n\n[[rules]]\n'
        'id = "identity_left"\n'
        'dir = "LEFT"\n'
        "inr = []\n"
        "trm = []\n"
        "cnd = []\n"
        'out = "(proj INR *)"\n',
        encoding="utf-8",
    )
    _write_alphabet_csv(
        tmp_path / "alphabet.csv",
        symbols=["A", "B"],
        features=["Voice"],
    )
    (tmp_path / "input.toml").write_text(
        'inputs = [["A"]]\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["compile", str(tmp_path)])
    assert result.exit_code == 0, result.output
    output_dir = tmp_path / "compiled"
    assert (output_dir / "identity_left.att").exists()
    assert (output_dir / "identity_left.sym").exists()
