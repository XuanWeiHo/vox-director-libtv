"""Strict local media probes shared by synthesis and assembly."""
import json
import subprocess


def probe_duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "json", str(path)], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    seconds = float(json.loads(result.stdout)["format"]["duration"])
    if seconds <= 0:
        raise ValueError(f"Media has no positive duration: {path}")
    return seconds
