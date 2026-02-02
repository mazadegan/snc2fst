import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--stress-test",
        action="store_true",
        default=False,
        help="Run stress tests (slow randomized backend comparisons).",
    )
    parser.addoption(
        "--stress-rules",
        type=int,
        default=50,
        help="Rule count for TvMachine stress tests.",
    )
    parser.addoption(
        "--stress-words",
        type=int,
        default=1000,
        help="Word count for TvMachine stress tests.",
    )
    parser.addoption(
        "--stress-max-len",
        type=int,
        default=15,
        help="Max word length for TvMachine stress tests.",
    )
    parser.addoption(
        "--stress-fst-rules",
        type=int,
        default=10,
        help="Rule count for OpenFst stress tests.",
    )
    parser.addoption(
        "--stress-fst-words",
        type=int,
        default=100,
        help="Word count for OpenFst stress tests.",
    )
    parser.addoption(
        "--stress-fst-max-len",
        type=int,
        default=12,
        help="Max word length for OpenFst stress tests.",
    )
    parser.addoption(
        "--stress-progress",
        action="store_true",
        default=True,
        help="Show progress bar for stress tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "stress: long-running randomized backend comparison tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--stress-test"):
        return
    skip_stress = pytest.mark.skip(
        reason="use --stress-test to run stress tests"
    )
    for item in items:
        if "stress" in item.keywords:
            item.add_marker(skip_stress)
