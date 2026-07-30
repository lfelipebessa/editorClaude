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


def has_audio(video: Path) -> bool:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    return bool(out.stdout.strip())


def build_filter(segments: list[dict], with_audio: bool) -> str:
    lines = []
    for i, seg in enumerate(segments):
        start, end = seg["start"], seg["end"]
        lines.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        if with_audio:
            lines.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")
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

    audio = has_audio(video)
    filter_graph = build_filter(segments, audio)

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
