from __future__ import annotations

import argparse
import subprocess
import threading
import webbrowser
from pathlib import Path

import uvicorn

from prepare_human_replay_data import prepare_human_replay_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the local human trading replay workstation.")
    parser.add_argument("--db", default="data/human_replay.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-ui-build", action="store_true", help="Use an existing ui/annotator/dist build.")
    args = parser.parse_args()
    default_replay_db = Path("data/human_replay.sqlite3")
    if args.db == str(default_replay_db) and not default_replay_db.exists():
        try:
            prepare_human_replay_data(
                Path("data/research.sqlite3"), default_replay_db,
                Path("app/config/research_periods.yaml"), Path("data/human_replay_manifest.json"),
            )
        except (ValueError, FileExistsError) as error:
            raise SystemExit(str(error)) from error
    ui_dir = Path(__file__).resolve().parents[1] / "ui" / "annotator"
    # Local research work must never silently serve an older frontend build.
    if not args.skip_ui_build:
        if not (ui_dir / "node_modules").exists(): subprocess.run(["npm", "install"], cwd=ui_dir, check=True)
        subprocess.run(["npm", "run", "build"], cwd=ui_dir, check=True)
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    # Importing the ASGI module creates its default app, so defer it until after
    # the missing replay database has been prepared above.
    from app.annotation.server import create_app
    uvicorn.run(create_app(args.db), host=args.host, port=args.port)


if __name__ == "__main__": main()
