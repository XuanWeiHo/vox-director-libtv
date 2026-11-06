"""Per-beat LibTV narration / voice reference and instrumental BGM."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from media_utils import probe_duration
from provider import get_provider, run_jobs
from libtv_provider import DEFAULTS, enum_values, save_json


def probe_dur(path):
    return probe_duration(path)


def run(project_dir):
    bpath = Path(project_dir) / "beats.json"
    doc = json.loads(bpath.read_text(encoding="utf-8-sig"))
    adir = Path(project_dir) / "audio"
    adir.mkdir(parents=True, exist_ok=True)
    prov = get_provider(doc.get("provider"), project_dir, config=doc)
    voice = doc.get("voice", {})
    model = voice.get("model", DEFAULTS["video"] if voice.get("clone_ref") else DEFAULTS["voice"])
    clone = prov.upload(voice["clone_ref"]) if voice.get("clone_ref") else None
    specs = {}
    for beat in doc["beats"]:
        # Explicit imported audio is supported; generated audio is cached by request hash.
        if beat.get("audio_source"):
            source = Path(beat["audio_source"]).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            duration = probe_dur(source)
            if beat.get("narration", "").strip() and duration < 0.25:
                raise RuntimeError(f"Beat {beat['id']}: imported narration is effectively empty")
            beat.update(narration_audio=str(source), narration_dur=duration)
            continue
        text = beat.get("narration", "")
        if not text.strip():
            silence = adir / f"narr_{beat['id']}.mp3"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", "0.1", str(silence)], check=True)
            beat.update(narration_audio=str(silence), narration_dur=0.1)
            continue
        params = dict(language=voice.get("language", doc.get("language", "zh")),
                      speed=voice.get("speed", 1.0))
        if clone:
            language = params["language"]
            seconds = voice.get("clone_duration") or max(4, min(30, math.ceil(len(text) / (3.5 if language == "zh" else 13) + 1)))
            text = ("Use @audio1 as the voice timbre reference. The same speaker speaks "
                    f"{language} in a clean dry studio voice, no music or sound effects. "
                    "Visual: a locked-off neutral paper backdrop, no text. "
                    "Speak the following NEW sentence exactly; do not repeat the reference words: " + text)
            specs[f"narr_{beat['id']}"] = lambda t=text, d=seconds: prov.submit_video(
                model, t, reference_audios=[clone], duration=d, ratio="16:9",
                resolution="480p", generate_audio=True)
            continue
        elif voice.get("voice_id"):
            params["voice_id"] = voice["voice_id"]
        specs[f"narr_{beat['id']}"] = lambda t=text, p=params: prov.submit_audio(model, text=t, **p)

    music = doc.get("music", "warm playful documentary instrumental, no vocals")
    if isinstance(music, dict) and music.get("source"):
        source = Path(music["source"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        doc.update(bgm_path=str(source), bgm_dur=probe_dur(source))
    elif music is False:
        silence = adir / "bgm-silence.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=stereo", "-t", "1", str(silence)], check=True)
        doc.update(bgm_path=str(silence), bgm_dur=1)
    else:
        cfg = music if isinstance(music, dict) else {"prompt": music}
        music_model = cfg.get("model", DEFAULTS["music"])
        _, schema = prov.model(music_model, "audio")
        prop = schema["properties"].get("duration", {})
        seconds = cfg.get("duration", sum(sum(s.get("dur", 5) for s in b.get("shots", [b]))
                                          for b in doc["beats"]))
        duration = seconds * 1000 if prop.get("originalField") == "music_length_ms" else seconds
        values = [v for v in enum_values(prop) if isinstance(v, (int, float)) and v > 0]
        if values:
            duration = next((v for v in sorted(values) if v >= duration), max(values))
        prompt = cfg.get("prompt", "documentary background") + ". Instrumental only, no vocals, no speech."
        options = {"duration": duration} if prop else {}
        specs["bgm"] = lambda: prov.submit_audio(music_model, prompt=prompt, **options)

    done = run_jobs(prov, specs)
    for beat in doc["beats"]:
        ref = done.get(f"narr_{beat['id']}")
        if ref:
            dest = adir / f"narr_{beat['id']}.mp3"
            prov.download(ref, dest)
            if probe_dur(dest) < 0.25:
                raise RuntimeError(f"Beat {beat['id']}: generated narration is effectively empty; inspect the input text")
            beat.update(narration_audio=str(dest), narration_audio_url=ref,
                        narration_dur=round(probe_dur(dest), 3))
    if done.get("bgm"):
        dest = adir / "bgm.mp3"
        prov.download(done["bgm"], dest)
        doc.update(bgm_path=str(dest), bgm_dur=probe_dur(dest))
    save_json(bpath, doc)


if __name__ == "__main__":
    run(os.path.abspath(sys.argv[1]))
