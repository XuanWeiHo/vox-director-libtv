"""Complete LibTV workflow: initialize, inspect, migrate, run and verify."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from libtv_provider import DEFAULTS, LibTVProvider, save_json
from provider import ProviderError


def read_doc(root):
    return json.loads((Path(root) / "beats.json").read_text(encoding="utf-8-sig"))


def init(root, source, project_id=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "beats.json"
    if dest.exists():
        raise FileExistsError(f"Project already exists: {dest}")
    doc = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    doc["provider"] = "libtv"
    cfg = doc.setdefault("libtv", {})
    if project_id:
        cfg["project_id"] = project_id
    else:
        prov = LibTVProvider(root, config=doc)
        receipt = root / ".libtv" / "canvas-create.json"
        if receipt.exists():
            raise ProviderError("Canvas creation was attempted already; inspect receipt and pass --project-id")
        save_json(receipt, {"status": "creating", "name": doc.get("project", root.name)})
        result = prov.cli("project", "create", doc.get("project", root.name))[-1]
        save_json(receipt, result)
        cfg["project_id"] = result["projectMeta"]["uuid"]
    save_json(dest, doc)
    print(dest)


def migrate(root):
    """Preserve original spec and local media; clear incompatible generated pointers."""
    root = Path(root)
    path = root / "beats.json"
    doc = read_doc(root)
    backup = root / "beats.before-libtv.json"
    if not backup.exists():
        shutil.copyfile(path, backup)
    doc.update(provider="libtv", image_model=DEFAULTS["image"], video_model=DEFAULTS["video"])
    doc.pop("video_model_fallback", None)
    doc["watermark"] = "Vox Director · LibTV"
    voice = doc.setdefault("voice", {})
    voice.pop("voice_id", None)
    voice["model"] = DEFAULTS["video"] if voice.get("clone_ref") else DEFAULTS["voice"]
    for field in ("bgm_path", "bgm_dur", "anchor_photo_url"):
        doc.pop(field, None)
    if doc.get("host"):
        doc["host"].update(person_video_model=DEFAULTS["video"], world_video_model=DEFAULTS["video"])
        doc["host"].pop("_avatar_urls", None)
    for beat in doc["beats"]:
        for obj in [beat, *beat.get("shots", [])]:
            for key in list(obj):
                if key.endswith(("_url", "_path")) or key in ("narration_audio", "narration_dur", "host_own_audio", "narration_audio_reference"):
                    obj.pop(key)
    save_json(path, doc)
    print(f"Migrated {path}; original preserved at {backup}")


def plan(doc):
    if doc.get("mode") == "aroll":
        return ["aroll_clips", "aroll_assemble"]
    host = any(s.get("kind") == "host" for b in doc["beats"] for s in b.get("shots", []))
    stages = ["audio"]
    if host:
        stages += ["host_plates", "host_clips"]
    stages += ["croll_keyframes" if doc.get("mode") == "croll" else "keyframes", "clips", "assemble"]
    return stages


def preflight(root):
    root = Path(root).resolve()
    doc = read_doc(root)
    if doc.get("provider", "libtv") != "libtv":
        raise ProviderError("Run migrate to convert the upstream project")
    for program in ("ffmpeg", "ffprobe"):
        if not shutil.which(program):
            raise ProviderError(f"Missing executable: {program}")
    from PIL import Image
    import numpy
    import text_overlay
    text_overlay._font(text_overlay.FONT_BOLD, 24)
    if not doc.get("beats"):
        raise ValueError("beats must not be empty")
    prov = LibTVProvider(root, config=doc)
    prov.require_project()
    # Exact project read via its node list; no writes, no generation.
    prov.cli("node", "list", "-p", prov.project)
    stage_list = plan(doc)
    models = {("image", doc.get("image_model", DEFAULTS["image"])),
              ("video", doc.get("video_model", DEFAULTS["video"]))}
    if "audio" in stage_list:
        voice = doc.get("voice", {})
        models.add(("video" if voice.get("clone_ref") else "audio", voice.get("model", DEFAULTS["video"] if voice.get("clone_ref") else DEFAULTS["voice"])))
        music = doc.get("music", {})
        if music is not False and not (isinstance(music, dict) and music.get("source")):
            models.add(("audio", music.get("model", DEFAULTS["music"]) if isinstance(music, dict) else DEFAULTS["music"]))
    if "host_clips" in stage_list:
        from host import validate, person_model, world_model
        validate(doc)
        models.update({("video", person_model(doc)), ("video", world_model(doc))})
    schemas = {}
    for kind, model in sorted(models):
        name, schema = prov.model(model, kind)
        schemas[name] = schema
    keys = set()
    for beat in doc["beats"]:
        if doc.get("mode") == "aroll":
            if not 0 <= beat["start"] < beat["end"]:
                raise ValueError("A-roll beat requires 0 <= start < end")
            continue
        if not isinstance(beat.get("narration"), str):
            raise ValueError(f"Beat {beat.get('id')} needs narration text")
        for shot in beat.get("shots") or [beat]:
            key = f"{beat['id']}{shot.get('id', '')}" if shot is not beat else str(beat["id"])
            if key in keys:
                raise ValueError(f"Duplicate shot key: {key}")
            keys.add(key)
            if not shot.get("scene"):
                raise ValueError(f"Shot {key} needs scene")
            if shot.get("kind") != "host":
                prov.normalize(doc.get("video_model", DEFAULTS["video"]), "video", "preflight",
                               dict(duration=shot.get("dur", 5), ratio=doc.get("aspect", "16:9"),
                                    resolution=doc.get("video_resolution", "720p"), generate_audio=False),
                               [{"kind": "image", "node": "validation-only"}])
    for key in ("anchor_photo", "source_video"):
        value = doc.get(key)
        if value and not value.startswith(("https://", "http://", "libtv://")) and not Path(value).is_file():
            raise FileNotFoundError(f"{key}: {value}; use an absolute media path")
    result = {"provider": "libtv", "project_id": prov.project, "stages": stage_list,
              "models": list(schemas), "generated": False}
    save_json(root / ".libtv" / "preflight.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def verify(root):
    root = Path(root)
    final = root / "final.mp4"
    if not final.is_file() or final.stat().st_size == 0:
        raise RuntimeError("final.mp4 is missing or empty")
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                          "-of", "json", str(final)], capture_output=True, text=True, check=True)
    meta = json.loads(raw.stdout)
    types = [s["codec_type"] for s in meta["streams"]]
    if "video" not in types or "audio" not in types:
        raise RuntimeError("Final film must contain video and audio")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(final),
                    "-f", "null", "-"], check=True, capture_output=True)
    from PIL import Image
    from hashlib import sha256
    seconds = float(meta["format"]["duration"])
    frames = []
    for i, t in enumerate((min(0.5, seconds/4), seconds/2, max(0, seconds-0.5))):
        frame = root / f"verify-{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(final),
                        "-frames:v", "1", "-vf", "scale=640:-2", str(frame)], check=True)
        with Image.open(frame) as image:
            image.verify()
        frames.append(str(frame.resolve()))
    report = {"path": str(final.resolve()), "bytes": final.stat().st_size,
              "sha256": sha256(final.read_bytes()).hexdigest(), "duration": seconds,
              "decode": "passed", "frames": frames,
              "visual_and_lipsync_review": "Inspect frames and listen to the delivered film"}
    save_json(root / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def approve_video(root, request_hash, confirmation):
    """Record a real user confirmation for one previously prepared request."""
    import datetime
    state = Path(root) / ".libtv" / "vox"
    path = state / f"video-plan-{request_hash}.json"
    if not path.is_file() or len(request_hash) != 64 or any(c not in "0123456789abcdef" for c in request_hash):
        raise ValueError("A valid existing video plan hash is required")
    if not confirmation.strip():
        raise ValueError("Record the user's explicit confirmation, not a generic continue")
    approvals = state / "video-approvals.json"
    granted = json.loads(approvals.read_text(encoding="utf-8")) if approvals.exists() else {}
    granted[request_hash] = {"confirmation": confirmation, "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save_json(approvals, granted)
    print(f"Recorded confirmation for {request_hash}; no generation submitted")


def run(root, execute=False):
    result = preflight(root)
    if not execute:
        print("Preflight only. Use --execute to run the displayed generation plan.")
        return
    for stage in result["stages"]:
        print(f"=== {stage} ===", flush=True)
        module = importlib.import_module(stage)
        if stage == "host_clips":
            module.run(str(Path(root).resolve()), confirmed=True)
        else:
            module.run(str(Path(root).resolve()))
    verify(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "migrate", "preflight", "run", "verify", "approve-video"):
        sub = commands.add_parser(name)
        sub.add_argument("project_dir")
        if name == "init":
            sub.add_argument("--spec", required=True)
            sub.add_argument("--project-id")
        if name == "run":
            sub.add_argument("--execute", action="store_true")
        if name == "approve-video":
            sub.add_argument("--request-hash", required=True)
            sub.add_argument("--confirmation", required=True)
    args = parser.parse_args()
    if args.command == "init":
        init(args.project_dir, args.spec, args.project_id)
    elif args.command == "approve-video":
        approve_video(args.project_dir, args.request_hash, args.confirmation)
    elif args.command == "run":
        run(args.project_dir, args.execute)
    else:
        globals()[args.command](args.project_dir)
