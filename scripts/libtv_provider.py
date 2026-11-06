"""Media requests -> CLI nodes, references, terminal receipts and local files.

Journal before dispatch; recover the same node after interruption. Never issue
another --run for a job whose outcome is unknown. No shell interpolation.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from provider import ProviderError

DEFAULTS = {"image": "General image V2", "video": "Seedance 2.5",
            "voice": "Minimax-speech-2.8-hd", "clone": "Seed Audio 1.0",
            "music": "Eleven Music V3"}


def json_objects(text):
    decoder, result, pos = json.JSONDecoder(), [], 0
    while pos < len(text):
        if text[pos] not in "{[":
            pos += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, pos)
        except ValueError:
            pos += 1
        else:
            result.append(obj)
            pos = end
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def enum_values(prop):
    return [x.get("value") if isinstance(x, dict) else x for x in prop.get("enum", [])]


class LibTVProvider:
    name = "libtv"

    def __init__(self, project_dir=None, config=None, runner=None):
        self.root = Path(project_dir or os.getcwd()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        docpath = self.root / "beats.json"
        self.doc = config if config is not None else (
            json.loads(docpath.read_text(encoding="utf-8-sig")) if docpath.exists() else {})
        self.cfg = self.doc.get("libtv", {})
        binding = self.root / ".libtv" / "project.json"
        bound = json.loads(binding.read_text(encoding="utf-8-sig")) if binding.exists() else {}
        self.project = self.cfg.get("project_id") or bound.get("projectUuid")
        self.exe = os.environ.get("LIBTV_CLI") or shutil.which("libtv")
        if not self.exe:
            raise ProviderError("libtv not found; set LIBTV_CLI or add it to PATH")
        self.state_dir = self.root / ".libtv" / "vox"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner or subprocess.run
        self.schemas, self.catalogs = {}, {}
        self.job_label = "media"

    def cli(self, *args):
        result = self.runner([self.exe, *map(str, args)], cwd=self.root,
                             stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        objects = json_objects(result.stdout)
        if result.returncode or (not objects and args[0] != "download"):
            raise ProviderError(f"libtv {' '.join(map(str, args[:2]))}: "
                                f"{(result.stderr or result.stdout)[-2500:]}")
        return objects

    def require_project(self):
        if not self.project:
            raise ProviderError("Set libtv.project_id in beats.json or run pipeline.py init")

    def require_video_approval(self, key, request):
        """Exact request consent, before creating OR running a video node.

        Cached completed results remain readable. Test/live calls default to
        requiring approval; callers cannot treat --execute as consent.
        """
        if not self.cfg.get("require_video_approval", True):
            return
        plan = self.state_dir / f"video-plan-{key}.json"
        save_json(plan, {"request_hash": key, "request": request})
        approvals = self.state_dir / "video-approvals.json"
        granted = json.loads(approvals.read_text(encoding="utf-8")) if approvals.exists() else {}
        if key not in granted:
            raise ProviderError(f"VIDEO_APPROVAL_REQUIRED: {plan}. "
                                "Show model, duration, prompt and references to the user; "
                                "record explicit confirmation before creating/running this video.")

    @contextmanager
    def lock(self):
        with open(self.state_dir / "execution.lock", "a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ProviderError("Another process is operating this project") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def model(self, name, kind):
        cache = (name, kind)
        if cache in self.schemas:
            return self.schemas[cache]
        if kind not in self.catalogs:
            self.catalogs[kind] = self.cli("model", "search", "-t", kind)[-1]["matches"]
        matches = [m for m in self.catalogs[kind] if name in (m["modelName"], m["modelKey"])]
        if len(matches) != 1:
            raise ProviderError(f"Model {name!r} is not a unique available {kind} model")
        found = matches[0]
        schema = self.cli("model", found["modelName"])[-1]["schema"]
        self.schemas[cache] = (found["modelName"], schema)
        return self.schemas[cache]

    def normalize(self, name, kind, prompt, params, refs):
        model, schema = self.model(name, kind)
        props = schema["properties"]
        out = {"model": model, "count": 1}
        if schema.get("scene"):
            out["scene"] = schema["scene"]
        limit = props.get("prompt", {}).get("maxLength", 0)
        if limit and len(prompt) > limit:
            raise ProviderError(f"Prompt exceeds {model}'s {limit} characters; split the beat")
        types = [r["kind"] for r in refs]
        mode = None
        if kind == "image":
            mode = "image2image" if refs else "text2image"
        elif kind == "video":
            if "video" in types:
                mode = "videoEdit2video"
            elif "audio" in types and "image" in types:
                mode = "mixed2video"
            elif "audio" in types:
                mode = "audio2video"
            elif len(refs) == 1:
                mode = "singleImage2video"
            else:
                mode = "image2video" if refs else "text2video"
        elif refs:
            mode = "audio2audio"
        modes = props.get("modeType", {}).get("items", {})
        settings = schema.get("config", {}).get("settings", {})
        if mode and modes and mode not in modes and (not isinstance(settings, dict) or mode not in settings):
            if mode == "singleImage2video" and "image2video" in modes:
                mode = "image2video"
            elif mode not in ("text2image", "text2video"):
                raise ProviderError(f"{model} does not expose {mode}; select a compatible model")
        if mode:
            out["modeType"] = mode
        if mode in modes:
            lo, hi = modes[mode]
            if not lo <= len(refs) <= hi:
                raise ProviderError(f"{model}/{mode} requires {lo}..{hi} references")

        def put(key, value):
            if value is None:
                return
            prop = props.get(key)
            if not isinstance(prop, dict):
                raise ProviderError(f"{model} does not expose parameter {key}")
            values = enum_values(prop)
            if ("min" in prop or "max" in prop) and not isinstance(value, (int, float)):
                raise ProviderError(f"{model}.{key} must be numeric")
            if values and value not in values:
                normalized = [v for v in values if str(v).lower() == str(value).lower()]
                if not normalized:
                    raise ProviderError(f"{model}.{key}={value!r}; allowed: {values}")
                value = normalized[0]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value < prop.get("min", float("-inf")) or value > prop.get("max", float("inf")):
                    raise ProviderError(f"{model}.{key}={value} outside schema limits")
                if prop.get("step"):
                    steps = (value - prop.get("min", 0)) / prop["step"]
                    if abs(steps - round(steps)) > 1e-7:
                        raise ProviderError(f"{model}.{key}={value} does not match step {prop['step']}")
            out[key] = value

        # CLI 1.1.3 routes FLAT schema property names; settings.foo is unsupported.
        ratio = params.pop("aspect_ratio", params.pop("ratio", None))
        resolution, duration = params.pop("resolution", None), params.pop("duration", None)
        if mode == "videoEdit2video":
            if "ratio_auto" in props:
                put("ratio_auto", "adaptive")
            if "duration_auto" in props:
                put("duration_auto", 0)
        else:
            put("ratio", ratio)
            put("duration", duration)
        if resolution is not None:
            put("quality" if kind == "image" and "quality" in props else "resolution", resolution)
        sound = params.pop("generate_audio", None)
        if sound is not None:
            put("enableSound", "on" if sound else "off")
        voice = params.pop("voice_id", None)
        if voice:
            put("voiceCard", {"voiceId": voice})
        elif kind == "audio" and "voiceCard" in props:
            put("voiceCard", props["voiceCard"]["default"])
        language = params.pop("language", None)
        if language and "language" in props:
            put("language", language)
        for key, value in params.items():
            put(key, value)
        return prompt, out

    def read_node(self, node):
        self.require_project()
        nodes = [o for o in self.cli("node", node, "-p", self.project)
                 if isinstance(o, dict) and o.get("nodeKey")]
        if len(nodes) != 1:
            raise ProviderError(f"Expected one exact node {node}, got {len(nodes)}")
        return nodes[0]

    def find_named(self, name):
        result = self.cli("node", "list", "-p", self.project)[-1]
        matches = [n for n in result.get("nodes", []) if n.get("name") == name]
        if len(matches) > 1:
            raise ProviderError(f"Ambiguous node name: {name}")
        return self.read_node(matches[0]["id"]) if matches else None

    @staticmethod
    def has_output(node):
        data = node.get("data", {})
        task = data.get("taskInfo", {})
        return bool(data.get("url")) and not task.get("loading", False) and task.get("status", 2) == 2

    def ref(self, source, kind=None):
        source = str(source)
        if source.startswith("libtv://"):
            project, node = source[8:].split("/", 1)
            if project != self.project:
                raise ProviderError("Reference belongs to another project; upload it explicitly")
            data = self.read_node(node)
            if not self.has_output(data):
                raise ProviderError(f"Reference {node} has no completed media")
            actual = data.get("nodeType") or data["data"]["type"]
            if kind and actual != kind:
                raise ProviderError(f"Expected {kind} reference, got {actual}")
            urls = data["data"]["url"]
            if len(urls) != 1:
                raise ProviderError("Reference contains multiple outputs; choose a single-output node")
            return {"node": node, "kind": actual, "content": digest(urls)}
        return self.ref(self.upload(source), kind)

    def submit(self, kind, model, prompt, refs=None, **params):
        self.require_project()
        resolved = [self.ref(src, media_kind) for src, media_kind in refs or []]
        numbered = {}
        for ref in resolved:
            numbered.setdefault(ref["kind"], []).append(ref["node"])
        def mention(match):
            media_kind, index = match.group(1), int(match.group(2)) - 1
            nodes = numbered.get(media_kind, [])
            if index >= len(nodes):
                raise ProviderError(f"Unbound reference {match.group(0)}")
            return "{{Node " + nodes[index] + "}}"
        prompt = re.sub(r"@(image|video|audio)(\d+)", mention, prompt)
        prompt, fields = self.normalize(model, kind, prompt, dict(params), resolved)
        request = {"project": self.project, "kind": kind, "prompt": prompt,
                   "params": fields, "refs": resolved, "label": self.job_label,
                   "revision": self.cfg.get("generation_revision", 0)}
        key = digest(request)
        path = self.state_dir / f"job-{key}.json"
        with self.lock():
            if path.exists():
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("node") and state["status"] in ("completed", "running", "unknown"):
                    node = self.read_node(state["node"])
                    if self.has_output(node):
                        fingerprint = digest(node["data"]["url"])
                        if state.get("output_digest") and state["output_digest"] != fingerprint:
                            raise ProviderError("Completed node output changed since this job; inspect the canvas before reuse")
                        state.update(status="completed", output=f"libtv://{self.project}/{state['node']}")
                        state["output_digest"] = fingerprint
                        save_json(path, state)
                        return key
                    raise ProviderError(f"Existing {state['status']} job {key[:12]} has no output; "
                                        "inspect its node. No resubmission.")
                if state["status"] == "creating":
                    existing = self.find_named(state["name"])
                    if existing:
                        state.update(node=existing["nodeKey"], status="prepared")
                        save_json(path, state)
                if state["status"] != "prepared":
                    raise ProviderError(f"Job {key[:12]} is {state['status']}; inspect its receipt")
                if kind == "video":
                    self.require_video_approval(key, request)
            else:
                # This gate is before any video-node mutation, including create.
                if kind == "video":
                    self.require_video_approval(key, request)
                state = {"request": request, "status": "creating", "node": None,
                         "name": f"vox-{kind}-{key[:20]}"}
                save_json(path, state)
                args = ["node", "create", state["name"], "-p", self.project,
                        "-t", kind, "--prompt", prompt]
                for field, value in fields.items():
                    args += ["-s", f"{field}={json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}"]
                for ref in resolved:
                    args += ["--left", ref["node"]]
                existing = self.find_named(state["name"])
                if existing:
                    if not self.has_output(existing):
                        raise ProviderError("Named job already exists without a result; inspect the original job")
                    state.update(node=existing["nodeKey"], status="completed",
                                 output=f"libtv://{self.project}/{existing['nodeKey']}",
                                 output_digest=digest(existing["data"]["url"]))
                    save_json(path, state)
                    return key
                receipts = self.cli(*args)
                nodes = [o for o in receipts if isinstance(o, dict) and (o.get("nodeKey") or o.get("newNodeKey"))]
                if len(nodes) != 1:
                    raise ProviderError("Node creation outcome unknown; inspect named node")
                state.update(node=nodes[0].get("nodeKey") or nodes[0]["newNodeKey"], status="prepared", create_receipt=nodes[0])
                save_json(path, state)
            state["status"] = "running"
            save_json(path, state)
            try:
                state["run_receipts"] = self.cli("node", state["node"], "-p", self.project, "--run")
                save_json(path, state)
                node = self.read_node(state["node"])
                if not self.has_output(node):
                    raise ProviderError("CLI ended without a completed output; receipt retained")
                state.update(status="completed", output=f"libtv://{self.project}/{state['node']}")
                state["output_digest"] = digest(node["data"]["url"])
            except BaseException as exc:
                state.update(status="unknown", error=str(exc))
                save_json(path, state)
                raise
            save_json(path, state)
        return key

    def submit_image(self, model, prompt, images=None, **params):
        return self.submit("image", model, prompt, [(s, "image") for s in images or []], **params)

    def submit_video(self, model, prompt, image=None, video=None, reference_images=None,
                     reference_videos=None, reference_audios=None, **params):
        refs = [(s, "image") for s in ([image] if image else []) + (reference_images or [])]
        refs += [(s, "video") for s in ([video] if video else []) + (reference_videos or [])]
        refs += [(s, "audio") for s in reference_audios or []]
        return self.submit("video", model, prompt, refs, **params)

    def submit_audio(self, model, text=None, prompt=None, references=None, **params):
        return self.submit("audio", model, text or prompt or "",
                           [(s, "audio") for s in references or []], **params)

    def get_status(self, job_id):
        state = json.loads((self.state_dir / f"job-{job_id}.json").read_text(encoding="utf-8"))
        return {"status": state["status"], "output": state.get("output"), "error": state.get("error")}

    def upload(self, path):
        self.require_project()
        path = str(path)
        if path.startswith("libtv://"):
            self.ref(path)
            return path
        if path.startswith(("https://", "http://")):
            from urllib.parse import urlparse
            suffix = Path(urlparse(path).path).suffix or ".bin"
            target = self.state_dir / ("source-" + digest(path) + suffix)
            if not target.exists():
                with urllib.request.urlopen(path, timeout=120) as response:
                    target.write_bytes(response.read())
            path = str(target)
        source = Path(path).expanduser().resolve()
        if not source.is_file() or not source.stat().st_size:
            raise ProviderError(f"Empty or missing source: {source}")
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        key = digest({"project": self.project, "sha256": sha})
        statefile = self.state_dir / f"upload-{key}.json"
        with self.lock():
            if statefile.exists():
                state = json.loads(statefile.read_text(encoding="utf-8"))
                if state.get("output"):
                    return state["output"]
                existing = self.find_named(state["name"])
                if existing and self.has_output(existing):
                    state.update(status="completed", output=f"libtv://{self.project}/{existing['nodeKey']}")
                    save_json(statefile, state)
                    return state["output"]
                raise ProviderError(f"Upload {key[:12]} outcome unknown; inspect {state['name']}")
            state = {"status": "uploading", "name": f"vox-source-{key[:20]}", "sha256": sha}
            existing = self.find_named(state["name"])
            if existing and self.has_output(existing):
                state.update(status="completed", output=f"libtv://{self.project}/{existing['nodeKey']}")
                save_json(statefile, state)
                return state["output"]
            if source.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
                self.require_video_approval(key, {"kind": "video_resource_upload", "project": self.project,
                    "source": str(source), "sha256": sha, "bytes": source.stat().st_size})
            save_json(statefile, state)
            values = self.cli("upload", state["name"], "-p", self.project, "-f", source)
            nodes = [v for v in values if isinstance(v, dict) and v.get("nodeKey")]
            state["receipts"] = values
            save_json(statefile, state)
            if len(nodes) != 1:
                raise ProviderError("Upload did not return exactly one nodeKey; receipt saved")
            node = self.read_node(nodes[0]["nodeKey"])
            if not self.has_output(node):
                raise ProviderError("Uploaded media not yet ready; do not re-upload")
            state.update(status="completed", output=f"libtv://{self.project}/{node['nodeKey']}")
            save_json(statefile, state)
            return state["output"]

    def download(self, reference, dest):
        from PIL import Image
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if str(reference).startswith("local://"):
            shutil.copyfile(str(reference)[8:], dest)
            return str(dest)
        ref = self.ref(reference)
        with tempfile.TemporaryDirectory(prefix="vox-download-", dir=self.state_dir) as tmp:
            self.cli("download", "-n", ref["node"], "-p", self.project, "-o", tmp)
            files = [p for p in Path(tmp).rglob("*") if p.is_file() and p.stat().st_size]
            if len(files) != 1 or files[0].suffix.lower() == ".zip":
                raise ProviderError(f"Expected one media file, got {len(files)}")
            source = files[0]
            if ref["kind"] == "image":
                with Image.open(source) as im:
                    if dest.suffix.lower() in (".jpg", ".jpeg"):
                        im.convert("RGB").save(dest, quality=95)
                    else:
                        im.save(dest)
            elif dest.suffix.lower() == ".mp3":
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source),
                                "-vn", "-c:a", "libmp3lame", str(dest)], check=True)
            else:
                shutil.copyfile(source, dest)
        if not dest.is_file() or not dest.stat().st_size:
            raise ProviderError(f"Download is empty: {dest}")
        return str(dest)

    def remove_bg(self, model, image_url, **params):
        from rembg import new_session, remove
        fingerprint = hashlib.sha256(Path(image_url).read_bytes()).hexdigest() if Path(image_url).is_file() else image_url
        key = digest({"remove_bg": fingerprint, "model": self.cfg.get("rembg_model", "u2netp")})
        source, dest = self.state_dir / f"rmbg-src-{key}.png", self.state_dir / f"rmbg-{key}.png"
        if not dest.exists():
            if Path(image_url).is_file():
                shutil.copyfile(image_url, source)
            else:
                self.download(image_url, source)
            session = new_session(self.cfg.get("rembg_model", "u2netp"))
            dest.write_bytes(remove(source.read_bytes(), session=session))
        save_json(self.state_dir / f"job-{key}.json",
                  {"status": "completed", "output": "local://" + str(dest)})
        return key
