"""Local faster-whisper transcription; real word timestamps, no cloud STT key."""
from pathlib import Path
import hashlib
import json
import subprocess
from libtv_provider import digest, save_json


def transcribe(source, cache_dir, language=None, keyterm=None, model="small", device="cpu"):
    from faster_whisper import WhisperModel
    source = Path(source).resolve()
    key = digest({"file": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "language": language, "keyterm": keyterm, "model": model})
    cache = Path(cache_dir) / f"asr-{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    engine = WhisperModel(model, device=device, compute_type="int8" if device == "cpu" else "float16")
    import numpy as np
    # Decode with the same ffmpeg used by the film pipeline; PyAV API versions
    # have changed independently of faster-whisper's audio helper.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True)
    waveform = np.frombuffer(raw.stdout, dtype=np.float32)
    segments, info = engine.transcribe(waveform, language=language, word_timestamps=True,
                                      vad_filter=True, initial_prompt=keyterm)
    words, text = [], []
    for segment in segments:
        text.append(segment.text)
        for word in segment.words or []:
            if word.end > word.start and word.word.strip():
                words.append({"text": word.word.strip(), "start": word.start, "end": word.end})
    result = {"text": "".join(text).strip(), "language": info.language, "words": words}
    if not words:
        raise RuntimeError("ASR returned no word timestamps; check the audio")
    save_json(cache, result)
    return result
