# snc2fst GUI — Design Notes

## Overview

The GUI is now the FastAPI web application served by `snc gui`. The CLI command starts a local server and opens the browser to the landing page. There is no parallel Textual application anymore.

## Current Shape

- `src/snc2fst/web/app.py` owns the HTTP routes and server-side rendering.
- `src/snc2fst/web/templates/` contains the Jinja templates for the welcome page, project view, and result partials.
- `src/snc2fst/web/static/` contains the CSS and browser-side assets.
- `snc gui` is the single GUI entrypoint.

## Core Flows

### Landing page

The landing page shows:
- primary actions to create a project or open an existing one through the browser
- recently opened projects from `~/.config/snc2fst/recent.json`
- starter templates for new project creation

### Project workspace

The project view provides:
- a file tree rooted at the project directory
- an editor for `config.toml`, CSVs, and related source files
- live validation status after saves
- eval and compile actions with results rendered into the page

### New project creation

The new-project form mirrors the CLI init flow:
- title, language, description, and sources
- optional starter selection
- target directory

Submitting the form creates the project files and redirects into the project workspace.

## Direction

Future GUI work should go into the web app only:
- expand browser-side editing ergonomics
- improve validation and result presentation
- add richer project navigation and authoring tools without reintroducing a terminal UI stack
