"""Conversa com o ffmpeg/ffprobe: sondagem de streams e medição de loudness.

Tudo que dispara um subprocesso mora aqui; o que só monta string mora em
core.filters. A separação é o que permite testar as cadeias sem tocar em mídia.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core.filters import build_audio_chain

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"


def parse_loudnorm_json(stderr: str) -> dict:
    """Extrai o bloco JSON que o loudnorm imprime no fim do stderr."""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end < start:
        sys.exit(f"loudnorm não imprimiu medição:\n{stderr[-800:]}")
    return json.loads(stderr[start:end + 1])


def measure_music_loudness(music: Path) -> float:
    """LUFS integrado da música (uma passada loudnorm, rápida)."""
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(music),
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    return float(parse_loudnorm_json(result.stderr)["input_i"])


def measure_loudness(video: Path, segments: list[dict], audio_idx: int,
                     audio_cfg: dict) -> dict:
    """Passada 1: mede loudness do áudio já cortado (só decodifica áudio)."""
    lines = []
    for i, seg in enumerate(segments):
        lines.append(f"[0:{audio_idx}]atrim=start={seg['start']}:end={seg['end']},"
                     f"asetpts=PTS-STARTPTS[a{i}];")
    inputs = "".join(f"[a{i}]" for i in range(len(segments)))
    lines.append(f"{inputs}concat=n={len(segments)}:v=0:a=1[acat];")
    lines.append(f"[acat]{build_audio_chain(audio_cfg, None)}[aout]")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines))
        script = f.name
    result = subprocess.run(
        [FFMPEG, "-i", str(video), "-filter_complex_script", script,
         "-map", "[aout]", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    Path(script).unlink(missing_ok=True)
    if result.returncode != 0:
        sys.exit(f"medição de loudness falhou:\n{result.stderr[-800:]}")
    return parse_loudnorm_json(result.stderr)


def pick_streams(video: Path) -> tuple[int, int | None]:
    """Seleciona a stream de vídeo principal e a primeira de áudio.

    Footage real (DJI, GoPro...) traz streams extras como thumbnail mjpeg
    (attached_pic) que não podem entrar no corte.
    """
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=index,codec_type:stream_disposition=attached_pic",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    video_idx, audio_idx = None, None
    for s in json.loads(out.stdout)["streams"]:
        attached = s.get("disposition", {}).get("attached_pic", 0)
        if s["codec_type"] == "video" and not attached and video_idx is None:
            video_idx = s["index"]
        elif s["codec_type"] == "audio" and audio_idx is None:
            audio_idx = s["index"]
    if video_idx is None:
        sys.exit("nenhuma stream de vídeo principal encontrada")
    return video_idx, audio_idx


def probe_resolution(video: Path, stream_idx: int) -> tuple[int, int]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", str(stream_idx),
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split(",")
    return int(w), int(h)
