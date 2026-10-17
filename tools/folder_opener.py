"""Open reviewbot run folders through a localhost link."""
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import math
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from paths import RUNS, WORK

PORT = 8765
RUN_ROOT = Path(RUNS).resolve()
TOKEN_FILE = Path(WORK) / "folder_opener_token.txt"

TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf8")

TOKEN = TOKEN_FILE.read_text(encoding="utf8").strip()

if not TOKEN:
    raise SystemExit("folder_opener_token.txt is empty")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # Do not print URLs containing the private token.
        pass

    def respond(self, status, text):
        body = text.encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        self.end_headers()
        self.wfile.write(body)

    def validate(self):
        if self.headers.get("Host") != f"127.0.0.1:{PORT}":
            self.respond(403, "Invalid host.")
            return None

        parts = urlsplit(self.path)
        match = re.fullmatch(
            r"/runs/([A-Za-z0-9][A-Za-z0-9_-]{0,99})"
            r"(?:/(video|sheet|battle-sheet1|play))?",
            parts.path
        )

        if not match:
            self.respond(404, "Unknown run link.")
            return None

        supplied = parse_qs(parts.query).get("key", [""])[0]
        if not hmac.compare_digest(
            supplied.encode("utf8"), TOKEN.encode("utf8")
        ):
            self.respond(403, "Invalid opening key.")
            return None

        run_id, action = match.groups()
        folder = (RUN_ROOT / run_id).resolve()

        if folder.parent != RUN_ROOT or not folder.is_dir():
            self.respond(404, "Run folder not found.")
            return None

        if action is None:
            return folder, "Folder"

        try:
            videos_file = folder / "videos.json"
            videos = (
                json.loads(videos_file.read_text(encoding="utf8"))
                if videos_file.is_file()
                else [{"file": "video0.mp4", "run_part": True}]
            )

            if not isinstance(videos, list) or not videos:
                raise ValueError("Invalid videos.json")

            if not all(isinstance(video, dict) for video in videos):
                raise ValueError("Invalid video entries")

            battle_index = next(
                (
                    index for index, video in enumerate(videos)
                    if video.get("role") == "battle"
                ),
                None,
            )

            if battle_index is None:
                battle_index = next(
                    (
                        index for index, video in enumerate(videos)
                        if video.get("run_part")
                    ),
                    0,
                )

            build_indices = []
            judge_file = folder / "judge.json"

            if judge_file.is_file():
                judged = json.loads(judge_file.read_text(encoding="utf8"))
                build_indices = judged.get("build_indices", [])

                if not isinstance(build_indices, list):
                    raise ValueError("Invalid build indices")

                if any(
                    type(index) is not int
                    or not 0 <= index < len(videos)
                    for index in build_indices
                ):
                    raise ValueError("Invalid build index")

            if not build_indices:
                build_indices = [
                    index for index, video in enumerate(videos)
                    if video.get("role") == "showcase"
                ] or [battle_index]

            selection_file = folder / "segment_selection.json"
            if selection_file.is_file():
                selection = json.loads(selection_file.read_text(encoding="utf8"))
                for key in ("battle_index", "build_index"):
                    selected = selection.get(key)
                    if selected is not None and (type(selected) is not int or not 0 <= selected < len(videos)):
                        raise ValueError("Invalid selected video index")
                battle_index = selection.get("battle_index", battle_index)
                if selection.get("build_index") is not None:
                    build_indices = [selection["build_index"]]

            play_index = battle_index
            query = parse_qs(parts.query)
            if "vid" in query:
                raw_index = query["vid"][0]
                if action not in ("video", "play") or not re.fullmatch(r"\d{1,6}", raw_index):
                    self.respond(400, "Invalid video index.")
                    return None
                play_index = int(raw_index)
                if not 0 <= play_index < len(videos):
                    self.respond(400, "Video index out of range.")
                    return None

            if action in ("video", "play"):
                relative = videos[play_index].get(
                    "file", f"video{play_index}.mp4"
                )

            elif action == "battle-sheet1":
                relative = f"sheet{battle_index}/01.jpg"

            else:
                # Use the build evidence selected by the judge.
                relative = next(
                    (
                        f"tabs{index}/sheet.jpg"
                        for index in build_indices
                        if (folder / f"tabs{index}/sheet.jpg").is_file()
                    ),
                    f"tabs{build_indices[0]}/sheet.jpg",
                )

            if not isinstance(relative, str) or not relative:
                raise ValueError("Invalid file path")

        except (OSError, ValueError, TypeError, AttributeError):
            self.respond(500, "Could not read run video metadata.")
            return None

        target = (folder / relative).resolve()
        if folder not in target.parents or not target.is_file():
            self.respond(404, "Requested file not found.")
            return None

        label = {
            "video": "Video",
            "play": "Video",
            "sheet": "Build sheet",
            "battle-sheet1": "Battle sheet",
        }[action]
        return target, label

    def do_GET(self):
        result = self.validate()
        if result is None:
            return

        target, label = result
        parts = urlsplit(self.path)

        if parts.path.endswith("/play"):
            try:
                seconds = float(
                    parse_qs(parts.query).get("t", ["0"])[0]
                )
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError()
            except (ValueError, TypeError):
                self.respond(400, "Invalid timestamp.")
                return

            try:
                subprocess.Popen([
                    "mpv",
                    f"--start={seconds}",
                    str(target),
                ])
            except OSError:
                self.respond(
                    500,
                    "Could not launch mpv. Check this helper's PATH."
                )
                return

            self.respond(
                200,
                "<h2>Opened in mpv.</h2>You can close this tab."
            )
            return

        try:
            os.startfile(str(target))
        except OSError:
            self.respond(500, "Could not open the requested item.")
            return

        self.respond(
            200,
            f"<h2>{label} opened.</h2>You can close this tab."
        )

    def do_POST(self):
        self.do_GET()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This helper is for Windows.")

    print(f"Folder opener running at http://127.0.0.1:{PORT}")
    print("Press Ctrl+C to stop.")

    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")