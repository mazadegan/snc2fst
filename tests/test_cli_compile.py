"""CLI integration tests for `snc compile`."""

import importlib.resources
import textwrap
import pytest
from pathlib import Path
from click.testing import CliRunner

from snc2fst.cli import main

pynini = pytest.importorskip("pynini", reason="pynini not installed")


@pytest.fixture(scope="module")
def starter_dir(tmp_path_factory):
    """Copy the english_plural starter into a temp directory."""
    tmp = tmp_path_factory.mktemp("english_plural")
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        dest = tmp / item.name
        dest.write_bytes(item.read_bytes())
    return tmp


@pytest.fixture(scope="module")
def config_path(starter_dir):
    return str(starter_dir / "config.toml")


@pytest.fixture(scope="module")
def compiled_dir(starter_dir, config_path):
    """Compile once for the whole module."""
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path])
    assert result.exit_code == 0, result.output
    return starter_dir / "transducers"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_compile_exits_zero(config_path, compiled_dir):
    assert compiled_dir.exists()


def test_compile_produces_fst_files(starter_dir, compiled_dir):
    fst_files = list(compiled_dir.glob("*.fst"))
    assert len(fst_files) > 0


def test_compile_produces_syms_files(compiled_dir):
    syms_files = list(compiled_dir.glob("*.syms"))
    assert len(syms_files) > 0


def test_compile_one_fst_per_rule(config_path, compiled_dir):
    import tomllib
    config = tomllib.loads(Path(config_path).read_text())
    rule_ids = [r["Id"] for r in config["rules"]]
    for rid in rule_ids:
        assert (compiled_dir / f"{rid}.fst").exists(), f"Missing {rid}.fst"
        assert (compiled_dir / f"{rid}.syms").exists(), f"Missing {rid}.syms"


def test_compile_idempotent(config_path, compiled_dir):
    """Running compile a second time overwrites cleanly."""
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --dir flag
# ---------------------------------------------------------------------------


def test_compile_custom_out_dir(starter_dir, config_path, tmp_path):
    out = tmp_path / "my_fsts"
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path, "--dir", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert len(list(out.glob("*.fst"))) > 0


# ---------------------------------------------------------------------------
# --format att
# ---------------------------------------------------------------------------


def test_compile_att_format(starter_dir, config_path, tmp_path):
    out = tmp_path / "att_fsts"
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path, "--dir", str(out), "--format", "att"])
    assert result.exit_code == 0
    assert len(list(out.glob("*.att"))) > 0


# ---------------------------------------------------------------------------
# --max-arcs guard
# ---------------------------------------------------------------------------


def test_compile_max_arcs_exceeded(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path, "--max-arcs", "1"])
    assert result.exit_code != 0
    assert "arcs" in result.output.lower() or "arcs" in (result.output + "").lower()


# ---------------------------------------------------------------------------
# Validation failure blocks compilation
# ---------------------------------------------------------------------------


def test_compile_blocked_by_invalid_config(tmp_path):
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp_path / item.name).write_bytes(item.read_bytes())

    config = (tmp_path / "config.toml").read_text()
    config += textwrap.dedent("""
        [[rules]]
        Id = "BadRule"
        Inr = [["+NOSUCHFEATURE"]]
        Trm = []
        Out = "INR[1]"
        Dir = "L"
    """)
    (tmp_path / "config.toml").write_text(config)

    runner = CliRunner()
    result = runner.invoke(main, ["compile", str(tmp_path / "config.toml")])
    assert result.exit_code != 0
