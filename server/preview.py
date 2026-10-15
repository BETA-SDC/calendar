"""Read-only development preview; never accepts a trusted account from HTTP."""
import argparse
from pathlib import Path

from flask import Flask, send_from_directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    @app.get("/calendar/")
    def index():
        return send_from_directory(args.site, "calendar.html")

    @app.get("/<path:asset>")
    def assets(asset):
        return send_from_directory(args.site, asset)

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
