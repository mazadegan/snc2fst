# snc2fst GUI — Design Notes

## Overview

A terminal-based GUI built with [Textual](https://textual.textualize.io/), accessible via `snc gui`. The GUI is the primary authoring interface: users should never need to edit `config.toml` by hand if they don't want to.

## Layout

**Left sidebar**
- Project overview: alphabet summary (segment count, feature count), rule list with pass/fail indicators from the last eval run
- Clicking a rule jumps to it in the main panel

**Main panel**
- Alphabet editor, rule editor, test suite — switchable via tabs or navigation

**Bottom-left tabs**
- **Errors/Warnings**: validation errors and warnings from the last `snc validate` run, updated live as you edit
- **Derivation trace**: step-by-step output when running a single word through the rules
- **Log**: compile output, arc counts, timing

**Right panel**
- Compile button with progress bar
- Eval controls: run test suite, single word input
- Export button (copies txt output to clipboard via `pyperclip`)

## Editing

### Alphabet editor
A spreadsheet-like grid. Clicking a cell cycles through `+` → `-` → `0` → `+`. Segments and features can be added/removed via dedicated buttons. Changes are saved back to `alphabet.csv` immediately.

### Rule editor
Form-based:
- **Inr/Trm**: visual natural class builder — click features to add them to a bundle, add bundles to the sequence
- **Dir**: dropdown (`L` / `R`)
- **Out**: Textual `TextArea` with live validation feedback — `collect_errors` runs on each keystroke and errors are shown inline below the editor. A tree-sitter grammar for the DSL would enable syntax highlighting.

### Test suite
Editable table backed by the project's test file (TSV or CSV). Clicking a cell overlays an `Input` widget pre-filled with the current value; pressing Enter commits and saves, Escape cancels. After editing an input or output cell, eval re-runs on that row automatically and updates the pass/fail indicator inline.

## Analytical Tools

### Rule interaction analysis
- **Feeding/bleeding detection**: statically check whether the output of rule A can create or destroy inputs for rule B, by comparing A's possible outputs against B's Inr
- **Ordering paradoxes**: flag pairs of rules where both A>B and B>A orderings produce different outputs on some input — surfaces counterfeeding/counterbleeding situations
- **Vacuous rule detection**: flag rules that never fire on any test case in the suite

### Alphabet/feature analysis
- **Natural class browser**: given a set of features, show which segments satisfy them — useful when writing Inr/Trm
- **Minimal pairs**: show which segments differ by exactly one feature — helps sanity-check the feature system
- **Underspecification visualization**: highlight `0` values in the alphabet matrix, with warnings for features that may cause unexpected natural class behavior

### Grammar-level tools
- **Coverage report**: which segments are ever targeted by a rule, which are never touched
- **Derivation browser**: across the full test suite, show all unique derivation paths — useful for spotting unexpected rule interactions

## Distribution

Shipped as part of the same conda package (`conda install mazadegan::snc2fst`). `snc gui` opens the app. `pyperclip` and `textual` added as dependencies. No separate installer needed.

## Project Management

### Creating a new project
A "New Project" screen (accessible from the welcome screen or command palette) replicates the `snc init` wizard as a proper form: text fields for title, language, description, and sources, a starter picker, and a directory picker for where to save. On submit, writes `config.toml`, `alphabet.csv`, and the appropriate tests file to the chosen directory and opens the project.

### Opening an existing project
"Open Project" launches a file browser using Textual's built-in `DirectoryTree` widget, navigating to a `config.toml`. Can also be triggered by passing a path directly: `snc gui config.toml`.

### Recent projects
A small JSON file at `~/.config/snc2fst/recent.json` tracks recently opened projects. The welcome screen lists them for quick access, similar to VS Code's recent workspaces.

### Saving
The GUI saves back to the project files on every committed change (alphabet cell toggle, rule form submit, test cell edit). `Ctrl+s` triggers an explicit save at any time.

## Command Palette

Accessible via `Ctrl+p`. Textual's built-in command palette supports fuzzy matching — typing `val` surfaces `validate`, `comp` shows `compile`, etc. Custom commands to register:

- `validate` — run validation
- `compile` — compile all rules
- `eval` — run test suite
- `export txt` / `export latex` — export in either format
- `add rule` — open a new rule form
- `add segment` — add a segment to the alphabet
- `open project` — load a different `config.toml`
- `natural class browser` — open the NC browser panel
- `switch theme` — built in

## Theme

Textual supports themes including Tokyo Night. Default theme TBD. Users can switch themes at runtime via the command palette (`Ctrl+p`).
