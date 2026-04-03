import importlib.resources
import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.suggester import Suggester
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical


# ---------------------------------------------------------------------------
# Recent projects
# ---------------------------------------------------------------------------

_RECENT_PATH = Path.home() / ".config" / "snc2fst" / "recent.json"
_MAX_RECENT = 5


def _load_recent() -> list[dict]:
    """Return list of recent projects [{title, path}, ...]."""
    if not _RECENT_PATH.exists():
        return []
    try:
        return json.loads(_RECENT_PATH.read_text())
    except Exception:
        return []


def _save_recent(entries: list[dict]) -> None:
    _RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RECENT_PATH.write_text(json.dumps(entries, indent=2))


def add_recent(title: str, config_path: Path) -> None:
    """Add a project to the recent list, deduplicating by path."""
    entries = _load_recent()
    entry = {"title": title, "path": str(config_path.resolve())}
    entries = [e for e in entries if e["path"] != entry["path"]]
    entries.insert(0, entry)
    _save_recent(entries[:_MAX_RECENT])


# ---------------------------------------------------------------------------
# Helpers shared by screens
# ---------------------------------------------------------------------------

def _resolve_language(raw: str) -> tuple[str, str | None]:
    """Resolve a language name or code to (iso_code, display_name).

    Returns (raw, None) if unrecognized.
    """
    import langcodes
    stripped = raw.strip()
    try:
        lang = langcodes.get(stripped)
        if lang.is_valid():
            return lang.to_alpha3(), lang.display_name()
    except Exception:
        pass
    try:
        found = langcodes.find(stripped)
        if found.is_valid():
            return found.to_alpha3(), found.display_name()
    except LookupError:
        pass
    return stripped, None


def _list_starters() -> list[str]:
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    return sorted(p.name for p in starters_dir.iterdir() if p.is_dir())


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_str_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{_toml_escape(s)}"' for s in items) + "]"


def _create_project(
    directory: Path,
    title: str,
    language: str,
    description: str,
    sources: list[str],
    starter: str | None,
) -> Path:
    """Create project files and return the path to config.toml."""
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    templates_dir = importlib.resources.files("snc2fst").joinpath("templates")
    config_path = directory / "config.toml"

    if starter:
        source_dir = starters_dir.joinpath(starter)
        import tomllib
        raw_config = tomllib.loads(source_dir.joinpath("config.toml").read_text())
        tests_filename = raw_config.get("tests_path", "tests.tsv")
        alphabet_filename = raw_config.get("alphabet_path", "alphabet.csv")
        source_files = [
            (config_path, source_dir.joinpath("config.toml")),
            (directory / alphabet_filename, source_dir.joinpath(alphabet_filename)),
            (directory / tests_filename, source_dir.joinpath(tests_filename)),
        ]
    else:
        source_files = [
            (config_path, templates_dir.joinpath("default_config.toml")),
            (directory / "alphabet.csv", templates_dir.joinpath("default_alphabet.csv")),
            (directory / "tests.tsv", templates_dir.joinpath("default_tests.tsv")),
        ]

    directory.mkdir(parents=True, exist_ok=True)
    contents = [(target, source.read_text()) for target, source in source_files]
    written: list[Path] = []
    try:
        for target_file, text in contents:
            target_file.write_text(text)
            written.append(target_file)
    except Exception as e:
        for f in written:
            f.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to write project files: {e}") from e

    if not starter:
        # Patch [meta] in the blank template.
        text = config_path.read_text(encoding="utf-8")
        text = text.replace('title = ""', f'title = "{_toml_escape(title)}"', 1)
        text = text.replace('language = ""', f'language = "{_toml_escape(language)}"', 1)
        text = text.replace('description = ""', f'description = "{_toml_escape(description)}"', 1)
        text = text.replace('sources = []', f'sources = {_toml_str_list(sources)}', 1)
        text = text.replace("\n# [meta] is filled in by `snc init` — do not edit manually.", "", 1)
        config_path.write_text(text, encoding="utf-8")

    return config_path


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------

class LangInput(Input):
    """Input that posts a FocusLost message when it loses focus."""

    class FocusLost(Message):
        pass

    def on_blur(self) -> None:
        self.post_message(self.FocusLost())


# ---------------------------------------------------------------------------
# Path suggester
# ---------------------------------------------------------------------------

class PathSuggester(Suggester):
    """Suggests filesystem directories as the user types a path."""

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        path = Path(value).expanduser()
        # If value ends with '/', complete inside that directory.
        if value.endswith("/"):
            parent, prefix = path, ""
        else:
            parent, prefix = path.parent, path.name
        try:
            matches = sorted(
                p for p in parent.iterdir()
                if p.is_dir() and p.name.startswith(prefix) and not p.name.startswith(".")
            )
        except (PermissionError, OSError):
            return None
        if not matches:
            return None
        suggestion = str(matches[0])
        # Preserve the ~ prefix if the user typed it.
        if value.startswith("~"):
            try:
                suggestion = "~/" + matches[0].relative_to(Path.home()).as_posix()
            except ValueError:
                pass
        return suggestion


# ---------------------------------------------------------------------------
# New Project screen
# ---------------------------------------------------------------------------

class NewProjectScreen(Screen):
    """Form for creating a new project."""

    TITLE = "New Project"
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._sources: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        starters = _list_starters()
        starter_options = [("Blank project", "")] + [(s, s) for s in starters]
        with ScrollableContainer(id="new-project-form"):
            yield Label("New Project", id="new-project-heading")
            yield Label("Title")
            yield Input(placeholder="My Grammar", id="np-title")
            yield Label("Language (name or ISO 639-3 code)")
            yield LangInput(placeholder="eng", id="np-lang")
            yield Label("Description (optional)")
            yield Input(placeholder="", id="np-desc")
            yield Label("Starter")
            yield Select(starter_options, value="", id="np-starter")
            yield Label("Directory")
            with Horizontal(id="np-dir-row"):
                yield Input(
                    placeholder="~/projects/my-grammar",
                    suggester=PathSuggester(use_cache=False),
                    id="np-dir",
                )
                yield Button("Browse…", id="btn-browse")
            yield Label("Sources (optional)", id="np-sources-label")
            yield Vertical(id="np-sources-list")
            with Horizontal(id="np-sources-controls"):
                yield Button("+ Add source", id="btn-add-source", variant="default")
            with Horizontal(id="np-submit-row"):
                yield Button("Create", id="btn-create", variant="primary")
                yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.app.pop_screen()
        elif event.button.id == "btn-browse":
            self.run_worker(self._browse_directory(), exclusive=True)
        elif event.button.id == "btn-add-source":
            self._add_source_row()
        elif event.button.id == "btn-create":
            self._submit()
        elif event.button.id and event.button.id.startswith("btn-remove-source-"):
            idx = int(event.button.id.split("-")[-1])
            self._remove_source_row(idx)

    async def _browse_directory(self) -> None:
        import asyncio
        import sys
        try:
            if sys.platform == "darwin":
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", "POSIX path of (choose folder)",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    path = stdout.decode().strip()
                    self.query_one("#np-dir", Input).value = path
            else:
                # Fallback: notify user to type the path manually.
                self.app.notify("Native folder picker is only available on macOS.", severity="warning")
        except Exception as e:
            self.app.notify(f"Could not open folder picker: {e}", severity="error")

    def _add_source_row(self) -> None:
        container = self.query_one("#np-sources-list", Vertical)
        idx = len(container.children)
        row = Horizontal(
            Input(placeholder="Author (Year) Title", id=f"np-source-{idx}"),
            Button("×", id=f"btn-remove-source-{idx}", variant="error"),
            id=f"np-source-row-{idx}",
        )
        container.mount(row)

    def _remove_source_row(self, idx: int) -> None:
        row = self.query_one(f"#np-source-row-{idx}", Horizontal)
        row.remove()

    def _collect_sources(self) -> list[str]:
        sources = []
        for inp in self.query_one("#np-sources-list", Vertical).query(Input):
            val = inp.value.strip()
            if val:
                sources.append(val)
        return sources

    def on_lang_input_focus_lost(self) -> None:
        inp = self.query_one("#np-lang", LangInput)
        raw = inp.value.strip()
        if not raw:
            return
        code, display = _resolve_language(raw)
        if display is not None and code != raw:
            inp.value = code
            self.app.notify(f"Resolved to {display} ({code})")
        elif display is None:
            self.app.notify(
                f"'{raw}' wasn't recognized as an ISO 639 code or language name — it'll be stored as-is.",
                severity="warning",
            )

    def _submit(self) -> None:
        title = self.query_one("#np-title", Input).value.strip()
        lang = self.query_one("#np-lang", Input).value.strip()
        desc = self.query_one("#np-desc", Input).value.strip()
        dir_str = self.query_one("#np-dir", Input).value.strip()
        starter_val = self.query_one("#np-starter", Select).value
        starter = starter_val if starter_val else None

        if not title:
            self.app.notify("Title is required.", severity="error")
            return
        if not lang:
            self.app.notify("Language is required.", severity="error")
            return
        if not dir_str:
            self.app.notify("Directory is required.", severity="error")
            return

        directory = Path(dir_str).expanduser().resolve()
        if directory.exists() and any(directory.iterdir()):
            self.app.notify(
                f"Directory '{directory}' is not empty.", severity="error"
            )
            return

        sources = self._collect_sources()
        try:
            config_path = _create_project(directory, title, lang, desc, sources, starter)
        except Exception as e:
            self.app.notify(str(e), severity="error")
            return

        add_recent(title, config_path)
        self.app.pop_screen()
        self.app.push_screen(ProjectScreen(config_path))


# ---------------------------------------------------------------------------
# Project screen (stub — main editor to be built here)
# ---------------------------------------------------------------------------

class ProjectScreen(Screen):
    """Main project editing screen."""

    BINDINGS = [("ctrl+w", "close", "Close project")]

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self._config_path = config_path

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Project: {self._config_path}", id="project-stub")
        yield Footer()

    def action_close(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Welcome screen
# ---------------------------------------------------------------------------

class WelcomeScreen(Screen):
    """Startup screen shown when no project is loaded."""

    TITLE = "Welcome"

    def compose(self) -> ComposeResult:
        yield Header()
        recent = _load_recent()
        yield Static(
            "╭─╮╭╮╷╭─╴╭─╮╭─╴╭─╮╶┬╴\n"
            "╰─╮│╰┤│  ╭─╯├╴ ╰─╮ │ \n"
            "╰─╯╵ ╵╰─╴╰─╴╵  ╰─╯ ╵ ",
            id="welcome-title",
        )
        yield Label("Search & Change rule authoring tool.", id="welcome-subtitle")
        with Center():
            yield Button("New Project", id="btn-new", variant="primary")
        with Center():
            yield Button("Open Project", id="btn-open")
        if recent:
            with Center():
                yield Label("Recent Projects", id="recent-label")
            with Center():
                yield ListView(
                    *[
                        ListItem(Label(f"{e['title']}  ({e['path']})"), id=f"recent-{i}")
                        for i, e in enumerate(recent)
                    ],
                    id="recent-list",
                )
        yield Footer()

    def on_mount(self) -> None:
        entries = _load_recent()
        broken = [e for e in entries if not Path(e["path"]).exists()]
        if not broken:
            return
        _save_recent([e for e in entries if Path(e["path"]).exists()])
        for e in broken:
            self.app.notify(
                f"Removed '{e['title']}' from recent — file not found: {e['path']}",
                severity="warning",
            )
        # Remove the stale items from the rendered list.
        try:
            lv = self.query_one("#recent-list", ListView)
            broken_paths = {e["path"] for e in broken}
            for item in list(lv.query(ListItem)):
                idx = int(item.id.split("-")[-1])
                if entries[idx]["path"] in broken_paths:
                    item.remove()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new":
            self.app.push_screen(NewProjectScreen())
        elif event.button.id == "btn-open":
            self.run_worker(self._pick_and_open(), exclusive=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = int(event.item.id.split("-")[-1])
        entry = _load_recent()[index]
        self.app.open_project(Path(entry["path"]))

    async def _pick_and_open(self) -> None:
        import asyncio
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e",
                'POSIX path of (choose file with prompt "Open snc2fst project")',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                path = Path(stdout.decode().strip())
                self.app.open_project(path)
        except Exception as e:
            self.app.notify(f"Could not open file picker: {e}", severity="error")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class SncApp(App):
    """snc2fst GUI."""

    TITLE = "snc2fst"
    CSS_PATH = "gui.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.push_screen(WelcomeScreen())

    def open_project(self, config_path: Path) -> None:
        """Validate and open a project, updating the recent list."""
        import tomllib
        from snc2fst.models import GrammarConfig
        from pydantic import ValidationError
        if config_path.suffix != ".toml":
            self.notify("Please select a .toml project file.", severity="error")
            return
        try:
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
            config = GrammarConfig(**raw)
        except FileNotFoundError:
            self.notify(f"File not found: {config_path}", severity="error")
            return
        except (tomllib.TOMLDecodeError, ValidationError) as e:
            self.notify(f"Invalid project file: {e}", severity="error")
            return
        title = getattr(getattr(config, "meta", None), "title", None) or config_path.stem
        add_recent(title, config_path)
        self.push_screen(ProjectScreen(config_path))


def run() -> None:
    SncApp().run()
