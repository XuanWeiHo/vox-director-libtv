#!/usr/bin/env python3
"""Cut source video into exact beats and edit through LibTV; preserve source timing for assembly."""
import json
import os
import subprocess
import sys

from provider import get_provider, run_jobs
from styles import resolve_theme, resolve_video_aspect
from media_utils import probe_duration

PRIMARY_MODEL = "Seedance 2.5"


def cut_segment(src, start, end, dest, pad=0):
    """Cut this beat's [start,end] (+ a small pad) out of the source, re-encoded
    so it's a clean, independently seekable upload for the video-edit call."""
    dur = max(end - start, 0.1) + pad
    ss = max(start - pad / 2, 0)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", src,
                    "-t", f"{dur:.2f}", "-c:v", "libx264", "-c:a", "aac",
                    "-pix_fmt", "yuv420p", dest], check=True)


def build_prompt(theme, content_beats=""):
    """Preserve the source performance while restyling the surrounding collage."""
    tp = theme or {}
    idiom = tp.get("idiom", "american-retro")
    palette = tp.get("palette", "bold retro primaries")
    type_style = tp.get("type_style", "bold condensed headlines")
    finish = tp.get("finish", "aged paper, high contrast")
    beats_line = f"\n\nCONTENT BEATS: {content_beats}" if content_beats else ""
    return (
        "Transform my raw talking-head video into a mixed-media collage motion graphic.\n\n"
        "TALKING-HEAD LOCK (most important):\n"
        "The presenter is a PHOTOGRAPHIC paper cut-out sticker with a bold black printed "
        "outline and a torn-paper silhouette edge -- their actual photographic likeness, "
        "facial performance, LIP MOVEMENTS, eye-line and hand gestures follow the source "
        "video frame-for-frame, unmodified. Do NOT re-texture, redraw, or halftone-print the "
        "face or skin itself -- only the silhouette edge and the world around them are paper-"
        "collage. Keep ALL motion, timing and framing from the source. Keep the presenter "
        "centered, matching the source video's own orientation.\n\n"
        f"STYLE (background & props): {idiom}. Palette: {palette}. Typography: {type_style}. "
        f"Finish: {finish}. Clearly layered hand-cut paper cut-outs with visible torn and "
        "scissor-cut edges, tape corners and soft real paper drop shadows, on a bold flat "
        "paper background. Halftone print dots, newspaper-clipping scraps, paper-stencil "
        "shapes, aged paper texture. PRINTED / illustrated cut-outs for the background and "
        f"props, NOT CGI, NOT 3D.{beats_line}\n\n"
        "CONSTRAINTS: background elements and stamps never cover their face or hands; "
        "everything except the presenter's face/skin reads as printed paper."
    )


def video_params(model, video_url, aspect, dur, resolution="720p"):
    """Keep original audio locally; the generated visual performance still needs review."""
    return dict(video=video_url, resolution=resolution, generate_audio=False)


def run(project_dir, only=None):
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath, encoding="utf-8-sig") as f:
        doc = json.load(f)
    if doc.get("mode") != "aroll":
        raise SystemExit("beats.json has no \"mode\": \"aroll\" -- run asr_beats.py first, "
                         "or use clips.py for a B-roll project.")
    src = doc["source_video"]
    aspect = doc.get("aspect", "9:16")
    theme = resolve_theme(doc.get("theme")) or {}
    primary = doc.get("video_model", PRIMARY_MODEL)
    seg_dir = os.path.join(project_dir, "segments")
    clip_dir = os.path.join(project_dir, "clips")
    os.makedirs(seg_dir, exist_ok=True)
    os.makedirs(clip_dir, exist_ok=True)

    prov = get_provider(doc.get("provider"), project_dir, config=doc)

    def gate_aspect(model):
        resolved, exact = resolve_video_aspect(aspect, model)
        if not exact and not doc.get("aspect_approx_confirmed"):
            print(f"ASPECT MISMATCH on {model}: project aspect \"{aspect}\" has no exact "
                  f"match; nearest supported is \"{resolved}\". Confirm with the user, then "
                  f"set \"aspect_approx_confirmed\": true in beats.json to proceed.")
            return None
        return resolved or aspect

    a_primary = gate_aspect(primary)
    if a_primary is None:
        return

    # ---- cut + upload each beat's segment, queue the primary-model submission ----
    specs, meta = {}, {}
    for beat in doc["beats"]:
        key = str(beat["id"])
        if only and key not in only:
            continue
        seg_path = os.path.join(seg_dir, f"seg_{key}.mp4")
        whole_source = (doc.get("source_node") and abs(beat["start"]) < 0.001 and
                        abs(beat["end"] - probe_duration(src)) < 0.05)
        if whole_source:
            # Explicit same-project original, already downloaded and reviewed.
            # No extra video-resource node is created for a full-source edit.
            prov.ref(doc["source_node"], "video")
            url = doc["source_node"]
            seg_path = src
        else:
            cut_segment(src, beat["start"], beat["end"], seg_path)
            url = prov.upload(seg_path)
        prompt = build_prompt(theme, beat.get("content_beats", ""))
        params = video_params(primary, url, a_primary, beat["dur"], doc.get("video_resolution", "720p"))
        specs[key] = (lambda m=primary, p=prompt, pr=params: prov.submit_video(m, p, **pr))
        meta[key] = {"beat": beat, "seg_path": seg_path, "url": url}
        print(f"[{key}] queued on {primary} ({beat['dur']}s)")

    done = run_jobs(prov, specs, poll_s=8, stall_s=240, max_retries=1, deadline_s=900)

    for key, url in done.items():
        beat = meta[key]["beat"]
        if not url:
            print(f"[{key}] FAILED on both primary and fallback -- beat will be missing "
                  f"from the assembled film")
            continue
        dest = os.path.join(clip_dir, f"clip_{key}.mp4")
        prov.download(url, dest)
        beat["clip_path"] = dest
        print(f"[{key}] saved {dest}")

    with open(bpath, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("updated", bpath)


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "out", "aroll-demo")
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    run(os.path.abspath(proj), only=only)
