"""Adaptador ffmpeg: aplica uma cut-list ao vídeo original e gera o rough cut.

Consome apenas o contrato da cut-list (ver README) — nunca o transcript.
Corta com precisão de frame usando trim/atrim + concat (re-encode).

Uso:
    python adapters/render_ffmpeg.py video.mp4 output/cutlist.json -o output/rough_cut.mp4
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"


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


def build_filter(segments: list[dict], video_idx: int, audio_idx: int | None) -> str:
    with_audio = audio_idx is not None
    lines = []
    for i, seg in enumerate(segments):
        start, end = seg["start"], seg["end"]
        lines.append(f"[0:{video_idx}]trim=start={start}:end={end},"
                     f"setpts=PTS-STARTPTS[v{i}];")
        if with_audio:
            lines.append(f"[0:{audio_idx}]atrim=start={start}:end={end},"
                         f"asetpts=PTS-STARTPTS[a{i}];")
    n = len(segments)
    if with_audio:
        inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        lines.append(f"{inputs}concat=n={n}:v=1:a=1[v][a]")
    else:
        inputs = "".join(f"[v{i}]" for i in range(n))
        lines.append(f"{inputs}concat=n={n}:v=1:a=0[v]")
    return "\n".join(lines)


def render(video: Path, cutlist: dict, output: Path) -> None:
    segments = cutlist["segments"]
    if not segments:
        sys.exit("cut-list sem segmentos: nada a renderizar")

    video_idx, audio_idx = pick_streams(video)
    filter_graph = build_filter(segments, video_idx, audio_idx)
    audio = audio_idx is not None

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(filter_graph)
        script = f.name

    cmd = [FFMPEG, "-y", "-i", str(video),
           "-filter_complex_script", script,
           "-map", "[v]"]
    if audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-movflags", "+faststart", str(output)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(script).unlink(missing_ok=True)
    if result.returncode != 0:
        sys.exit(f"ffmpeg falhou:\n{result.stderr[-2000:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("output/rough_cut.mp4"))
    args = parser.parse_args()

    if not args.video.exists():
        sys.exit(f"vídeo não encontrado: {args.video}")
    cutlist = json.loads(args.cutlist.read_text())
    if cutlist.get("version") != 1:
        sys.exit(f"versão de cut-list não suportada: {cutlist.get('version')}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(args.video, cutlist, args.output)

    stats = cutlist.get("stats", {})
    print(f"rough cut salvo em {args.output} "
          f"({len(cutlist['segments'])} segmentos, "
          f"~{stats.get('kept_duration', '?')}s mantidos)")


if __name__ == "__main__":
    main()
