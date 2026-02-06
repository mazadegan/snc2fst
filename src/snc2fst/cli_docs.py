"""Helpers for Sphinx CLI docs."""

from typer.main import get_command

from .main import app

cli = get_command(app)
