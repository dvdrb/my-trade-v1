from __future__ import annotations

import argparse
import subprocess
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.annotation.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the local human trading replay workstation.")
    parser.add_argument("--db", default="data/human_replay.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-ui-build", action="store_true", help="Use an existing ui/annotator/dist build.")
    args = parser.parse_args()
    ui_dir = Path(__file__).resolve().parents[1] / "ui" / "annotator"
    # Local research work must never silently serve an older frontend build.
    if not args.skip_ui_build:
        if not (ui_dir / "node_modules").exists(): subprocess.run(["npm", "install"], cwd=ui_dir, check=True)
        subprocess.run(["npm", "run", "build"], cwd=ui_dir, check=True)
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(args.db), host=args.host, port=args.port)


if __name__ == "__main__": main()
