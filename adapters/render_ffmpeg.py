"""Adaptador ffmpeg: aplica uma cut-list ao vídeo original e gera o rough cut.

Consome apenas o contrato da cut-list (ver README) — nunca o transcript.
Corta com precisão de frame usando trim/atrim + concat (re-encode).

As cadeias de filtro, a leitura do style e a medição de loudness vivem em
`core/` — este arquivo é só o adaptador de linha de comando.

Uso:
    python adapters/render_ffmpeg.py video.mp4 output/cutlist.json -o output/rough_cut.mp4
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core import (FFMPEG, build_audio_chain, build_color_chain, build_filter,
                  build_finish_chain, load_style, measure_loudness,
                  pick_platform, pick_streams, probe_resolution,
                  vertical_filter)


def render(video: Path, cutlist: dict, output: Path,
           platform: dict | None = None, x_offset: int = 0,
           audio_cfg: dict | None = None, color_cfg: dict | None = None) -> None:
    segments = cutlist["segments"]
    if not segments:
        sys.exit("cut-list sem segmentos: nada a renderizar")

    video_idx, audio_idx = pick_streams(video)
    filter_graph = build_filter(segments, video_idx, audio_idx)
    audio = audio_idx is not None

    map_video = "[v]"
    if color_cfg:
        chain = build_color_chain(color_cfg)
        if chain:
            filter_graph += f";\n{map_video}{chain}[vc]"
            map_video = "[vc]"
    if platform and platform.get("transform") != "none" and "width" in platform:
        src_w, src_h = probe_resolution(video, video_idx)
        filter_graph += f";\n{map_video}{vertical_filter(src_w, src_h, platform, x_offset)}[vf]"
        map_video = "[vf]"
    if color_cfg:
        finish = build_finish_chain(color_cfg)
        if finish:
            filter_graph += f";\n{map_video}{finish}[vt]"
            map_video = "[vt]"

    map_audio = "[a]"
    if audio and audio_cfg:
        print("medindo loudness do corte (passada 1)...")
        measured = measure_loudness(video, segments, audio_idx, audio_cfg)
        print(f"  antes: I={measured['input_i']} LUFS, TP={measured['input_tp']} dBTP, "
              f"LRA={measured['input_lra']}")
        filter_graph += f";\n[a]{build_audio_chain(audio_cfg, measured)}[af]"
        map_audio = "[af]"

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(filter_graph)
        script = f.name

    cmd = [FFMPEG, "-y", "-i", str(video),
           "-filter_complex_script", script,
           "-map", map_video]
    if audio:
        cmd += ["-map", map_audio, "-c:a", "aac", "-b:a", "192k"]
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
    parser.add_argument("--style", default="seco",
                        help="style em styles/ de onde vem a configuração de plataformas")
    parser.add_argument("--platform", default=None,
                        help="plataforma alvo do style (ex.: instagram, tiktok); omitir = original")
    parser.add_argument("--crop-x-offset", type=int, default=None,
                        help="desloca o crop central em pixels do vídeo fonte (+ = direita); "
                             "sobrepõe o crop_x_offset do style")
    parser.add_argument("--no-audio-norm", action="store_true",
                        help="não aplica a cadeia de áudio do style (loudnorm+limiter)")
    parser.add_argument("--no-color", action="store_true",
                        help="não aplica a cadeia de cor do style (LUT+ajustes)")
    args = parser.parse_args()

    if not args.video.exists():
        sys.exit(f"vídeo não encontrado: {args.video}")
    cutlist = json.loads(args.cutlist.read_text())
    if cutlist.get("version") != 1:
        sys.exit(f"versão de cut-list não suportada: {cutlist.get('version')}")

    style = load_style(args.style)
    platform = pick_platform(style, args.platform) if args.platform else None
    x_offset = args.crop_x_offset
    if x_offset is None:
        x_offset = platform.get("crop_x_offset", 0) if platform else 0
    audio_cfg = None if args.no_audio_norm else style.get("audio")
    color_cfg = None if args.no_color else style.get("color")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(args.video, cutlist, args.output, platform, x_offset, audio_cfg, color_cfg)

    stats = cutlist.get("stats", {})
    print(f"rough cut salvo em {args.output} "
          f"({len(cutlist['segments'])} segmentos, "
          f"~{stats.get('kept_duration', '?')}s mantidos)")


if __name__ == "__main__":
    main()
