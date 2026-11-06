"""Build a portable .skill archive without credentials, outputs or local venv."""
import argparse
from pathlib import Path
import zipfile


def package(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [root / n for n in ("SKILL.md", "AGENTS.md", "README.md", "LICENSE", "requirements.txt")]
    for folder, pattern in (("scripts", "*.py"), ("references", "*.md"), ("examples", "*.json")):
        files += sorted((root / folder).glob(pattern))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, "vox-director-libtv/" + path.relative_to(root).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive CRC verification failed")
    print(f"{output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="vox-director-libtv.skill")
    args = parser.parse_args()
    package(Path(__file__).resolve().parents[1], args.output)
