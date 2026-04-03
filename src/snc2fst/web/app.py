"""FastAPI web application for snc2fst."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from snc2fst.project import (
    add_recent,
    load_recent,
    resolve_language,
    list_starters,
    create_project,
    run_eval,
    run_compile,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI()

_static_dir = Path(__file__).parent / "static"
_templates_dir = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_templates_dir))


def _r(request: Request, name: str, ctx: dict) -> HTMLResponse:
    """Render a template with the new Starlette TemplateResponse signature."""
    return templates.TemplateResponse(request, name, ctx)


# ---------------------------------------------------------------------------
# Welcome / recent projects
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def welcome(request: Request):
    return _r(request, "welcome.html", {
        "recent": load_recent(),
        "starters": list_starters(),
    })


# ---------------------------------------------------------------------------
# Project view
# ---------------------------------------------------------------------------

@app.get("/project", response_class=HTMLResponse)
async def project_view(request: Request, path: str):
    config_path = Path(path)
    if not config_path.exists():
        return HTMLResponse("Project not found.", status_code=404)

    from snc2fst.cli import _run_validate

    validation = await asyncio.to_thread(_run_validate, config_path)
    title = config_path.parent.name
    if validation.config is not None:
        title = validation.config.meta.title or title
    add_recent(title, config_path)

    tree = _build_tree(config_path.parent, config_path)
    file_content = config_path.read_text()

    return _r(request, "project.html", {
        "config_path": str(config_path),
        "project_dir": str(config_path.parent),
        "title": title,
        "tree": tree,
        "active_file": str(config_path),
        "file_content": file_content,
        "file_name": config_path.name,
        "ok": validation.ok,
        "errors": validation.errors,
        "warnings": validation.warnings,
    })


# ---------------------------------------------------------------------------
# File API
# ---------------------------------------------------------------------------

@app.get("/api/file", response_class=HTMLResponse)
async def get_file(request: Request, path: str, config_path: str):
    file_path = Path(path)
    try:
        content = file_path.read_text()
    except Exception as e:
        return HTMLResponse(f"Error reading file: {e}", status_code=400)
    return _r(request, "partials/editor.html", {
        "file_content": content,
        "active_file": path,
        "file_name": file_path.name,
        "config_path": config_path,
    })


@app.post("/api/file", response_class=HTMLResponse)
async def save_file(
    request: Request,
    path: str = Form(...),
    content: str = Form(...),
    config_path: str = Form(...),
):
    try:
        Path(path).write_text(content)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from snc2fst.cli import _run_validate
    result = await asyncio.to_thread(_run_validate, Path(config_path))
    return _r(request, "partials/status.html", {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
    })


# ---------------------------------------------------------------------------
# Directory tree partial
# ---------------------------------------------------------------------------

@app.get("/api/tree", response_class=HTMLResponse)
async def get_tree(request: Request, path: str, config_path: str, active_file: str | None = None):
    tree = _build_tree(Path(path), Path(active_file) if active_file else None)
    return _r(request, "partials/tree.html", {
        "tree": tree,
        "config_path": config_path,
        "active_file": active_file,
    })


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@app.post("/api/validate", response_class=HTMLResponse)
async def validate(request: Request, config_path: str = Form(...)):
    from snc2fst.cli import _run_validate
    result = await asyncio.to_thread(_run_validate, Path(config_path))
    return _r(request, "partials/status.html", {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
    })


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

@app.post("/api/eval", response_class=HTMLResponse)
async def eval_route(
    request: Request,
    config_path: str = Form(...),
    use_fst: bool = Form(False),
):
    rows, passed, failed, errors = await asyncio.to_thread(
        run_eval, Path(config_path), use_fst
    )
    return _r(request, "partials/eval_results.html", {
        "rows": rows,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
    })


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

@app.post("/api/compile", response_class=HTMLResponse)
async def compile_route(
    request: Request,
    config_path: str = Form(...),
    fmt: str = Form("fst"),
    max_arcs: int = Form(1_000_000),
    no_optimize: bool = Form(False),
):
    rows, out_path, error = await asyncio.to_thread(
        run_compile, Path(config_path), fmt, max_arcs, no_optimize
    )
    return _r(request, "partials/compile_results.html", {
        "rows": rows,
        "out_path": str(out_path) if out_path else None,
        "error": error,
    })


# ---------------------------------------------------------------------------
# New project
# ---------------------------------------------------------------------------

@app.post("/api/project/new")
async def new_project(
    request: Request,
    title: str = Form(...),
    language: str = Form(...),
    description: str = Form(""),
    directory: str = Form(...),
    starter: str = Form(""),
    sources: str = Form(""),
):
    lang_code, _ = resolve_language(language)
    source_list = [s.strip() for s in sources.splitlines() if s.strip()]
    try:
        config_path = await asyncio.to_thread(
            create_project,
            Path(directory).expanduser().resolve(),
            title,
            lang_code,
            description,
            source_list,
            starter or None,
        )
    except Exception as e:
        return _r(request, "partials/new_project_error.html", {"error": str(e)})
    add_recent(title, config_path)
    return RedirectResponse(url=f"/project?path={config_path}", status_code=303)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_tree(directory: Path, active_file: Path | None = None) -> list[dict]:
    """Return a nested tree for the directory."""
    entries = []
    try:
        for p in sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if p.name.startswith(".") or p.name == "__pycache__":
                continue
            node = {
                "path": str(p),
                "name": p.name,
                "is_dir": p.is_dir(),
            }
            if p.is_dir():
                children = _build_tree(p, active_file)
                node["children"] = children
                node["is_open"] = any(
                    child.get("is_active") or child.get("is_open") for child in children
                )
                node["icon"] = "folder-open" if node["is_open"] else "folder"
            else:
                node["is_active"] = active_file is not None and p == active_file
                if p.suffix == ".toml":
                    node["icon"] = "file-code-2"
                elif p.suffix in {".csv", ".tsv"}:
                    node["icon"] = "table-properties"
                else:
                    node["icon"] = "file"
            entries.append(node)
    except PermissionError:
        pass
    return entries
