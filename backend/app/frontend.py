"""Serve the built web app (frontend/dist) from FastAPI, so one service does everything."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def serve_frontend(app: FastAPI, dist: Path) -> bool:
    """Add a route that serves the built frontend. Does nothing (and returns False) if the
    frontend has not been built. Must be called after the /api routes are added, because it
    answers every other path."""
    if not (dist / "index.html").is_file():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "There is no such API route.")
        file = (root / path).resolve()
        # A real file inside the build folder (a script, a stylesheet, an icon) is sent as
        # it is. A request can never reach a file outside that folder.
        if file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        # Anything else is a screen of the app, such as /runs/<id>: the app itself works out
        # which screen to show, so every such address gets the same page.
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return True
