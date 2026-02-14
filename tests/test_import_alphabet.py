import sys
from pathlib import Path

from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app  # noqa: E402


def test_validate_csv_example(tmp_path: Path) -> None:
    csv_content = ", a, b, c\nvoice, +, -, 0\nnasal, 0, +, -\n"
    table_path = tmp_path / "table.csv"
    table_path.write_text(csv_content, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["validate", "alphabet", str(table_path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"


def test_validate_tsv_example(tmp_path: Path) -> None:
    tsv_content = "\ta\tb\tc\nvoice\t+\t-\t0\nnasal\t0\t+\t-\n"
    table_path = tmp_path / "table.tsv"
    table_path.write_text(tsv_content, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["validate", "alphabet", str(table_path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "OK"
