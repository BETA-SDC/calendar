"""Prepare or verify an offline Python 3.12 / Linux x86_64 dependency bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def requirements_digest():
    digest = hashlib.sha256()
    for name in ("requirements.txt", "requirements-server.txt", "requirements-deploy.txt"):
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def verify(output):
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["requirements"] != requirements_digest() or not manifest["files"]:
        raise ValueError("Offline dependencies are stale or empty; prepare them again.")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("Invalid wheel filename.")
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Offline dependency checksum mismatch: {name}")
    if set(manifest["files"]) != {path.name for path in output.glob("*.whl")}:
        raise ValueError("Unexpected wheels in offline dependency directory.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "work/wheels")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                        "--platform", "manylinux2014_x86_64", "--implementation", "cp",
                        "--python-version", "3.12", "--dest", str(args.output),
                        "-r", str(ROOT / "requirements-deploy.txt")], check=True)
        manifest = {"requirements": requirements_digest(), "files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(args.output.glob("*.whl"))
        }}
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify(args.output)
    print("Offline dependency bundle verified.")


if __name__ == "__main__":
    main()
