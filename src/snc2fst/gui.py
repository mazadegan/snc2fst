import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static
from textual.containers import Center


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
            yield Label("Recent Projects", id="recent-label")
            yield ListView(
                *[
                    ListItem(Label(f"{e['title']}  ({e['path']})"), id=f"recent-{i}")
                    for i, e in enumerate(recent)
                ],
                id="recent-list",
            )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new":
            self.app.notify("New Project — coming soon.")
        elif event.button.id == "btn-open":
            self.app.notify("Open Project — coming soon.")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = int(event.item.id.split("-")[-1])
        entry = _load_recent()[index]
        self.app.notify(f"Opening {entry['title']} — coming soon.")


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
        self.push_screen(WelcomeScreen())


def run() -> None:
    SncApp().run()
