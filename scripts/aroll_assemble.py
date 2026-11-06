#!/usr/bin/env python3
"""Assemble edited visuals with original source audio; reject missing or short clips."""
import json
import os
import subprocess
import sys
from media_utils import probe_duration
import text_overlay

RES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
       "4:3": (1440, 1080), "3:4": (1080, 1440)}


def ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def probe_dur(path):
    return probe_duration(path)


def run(project_dir):
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath, encoding="utf-8-sig") as f:
        doc = json.load(f)
    src = doc["source_video"]
    W, H = doc.get("output_size") or RES[doc.get("aspect", "9:16")]
    tmp = os.path.join(project_dir, "_seg")
    os.makedirs(tmp, exist_ok=True)

    muxed = []
    for beat in doc["beats"]:
        clip = beat.get("clip_path")
        if not clip or not os.path.exists(clip):
            raise RuntimeError(f"[{beat['id']}] missing clip; refusing an incomplete film")
        audio_path = os.path.join(tmp, f"audio_{beat['id']}.aac")
        ff(["-ss", f"{beat['start']:.2f}", "-i", src, "-t", f"{beat['dur']:.2f}",
            "-vn", "-c:a", "aac", audio_path])
        vd, ad = probe_dur(clip), probe_dur(audio_path)
        d = float(beat["dur"])
        if abs(vd - d) > max(0.15, 2 / 24):
            raise RuntimeError(f"[{beat['id']}] edited duration {vd}s differs from source {d}s; "
                               "review the source and generated performance, no silent retiming")
        if not d:
            print(f"[{beat['id']}] couldn't probe a duration -- skipped")
            continue
        # normalize every beat to the same canvas (models may return different
        # native sizes even at the same aspect) so the final concat is safe
        out = os.path.join(tmp, f"muxed_{beat['id']}.mp4")
        fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},setsar=1,fps=24[v]")
        inputs = ["-i", clip, "-i", audio_path]
        if doc.get("captions", True) and beat.get("text"):
            caption = os.path.join(tmp, f"caption_{beat['id']}.png")
            text_overlay.render_caption(beat["text"], caption, W, H, style=doc.get("caption_style", "white"))
            inputs += ["-i", caption]
            fc = fc.replace("[v]", "[base]") + ";[base][2:v]overlay=0:0[v]"
        ff([*inputs, "-filter_complex", fc, "-map", "[v]", "-map", "1:a:0",
            "-t", f"{d:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out])
        muxed.append(out)
        print(f"[{beat['id']}] muxed ({d:.2f}s)")

    if not muxed:
        raise SystemExit("no beats had a generated clip -- run aroll_clips.py first")

    listf = os.path.join(tmp, "concat_list.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for m in muxed:
            escaped = os.path.abspath(m).replace(chr(92), "/").replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))
            f.write(f"file '{escaped}'\n")
    final = os.path.join(project_dir, "final.mp4")
    ff(["-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", final])
    print("FINAL:", final, f"({len(muxed)}/{len(doc['beats'])} beats)")


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "out", "aroll-demo")
    run(os.path.abspath(proj))
