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
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = PROJECT_ROOT / "styles"


def load_style(style_name: str) -> dict:
    path = STYLES_DIR / f"{style_name}.json"
    if not path.exists():
        sys.exit(f"style não encontrado: {path}")
    return json.loads(path.read_text())


def pick_platform(style: dict, platform: str) -> dict:
    platforms = style.get("platforms", {})
    if platform not in platforms:
        sys.exit(f"plataforma '{platform}' não existe no style "
                 f"(disponíveis: {', '.join(sorted(platforms))})")
    return platforms[platform]


def build_color_chain(color_cfg: dict) -> str:
    """Cadeia de cor a partir do style: LUT (se configurada) + ajustes pós.

    scope=camera: só footage de câmera recebe tratamento — motion graphics
    nunca passam por aqui (o composer futuro usa este flag para rotear).
    """
    parts = []
    lut = color_cfg.get("lut")
    if lut:
        lut_path = Path(lut)
        if not lut_path.is_absolute():
            lut_path = PROJECT_ROOT / lut_path
        if not lut_path.exists():
            sys.exit(f"LUT configurada no style não encontrada: {lut_path}")
        parts.append(f"lut3d=file={lut_path}")
    adjust = color_cfg.get("adjust", {})
    curve = adjust.get("curve_s")
    if curve:
        parts.append(f"curves=master='{curve}'")
    whites = adjust.get("whites", 0)
    blacks = adjust.get("blacks", 0)
    if whites or blacks:
        # aproximação dos sliders Whites/Blacks do Lumetri (escala -100..100):
        # blacks<0 esmaga o preto (sobe o ponto de entrada), whites>0 acende o
        # branco (desce o teto de entrada). Direções opostas não suportadas.
        imin = round(max(0.0, -blacks * 0.003), 3)
        imax = round(min(1.0, 1 - whites * 0.003), 3)
        parts.append(f"colorlevels=rimin={imin}:gimin={imin}:bimin={imin}:"
                     f"rimax={imax}:gimax={imax}:bimax={imax}")
    vibrance = adjust.get("vibrance", 0.0)
    if vibrance:
        parts.append(f"vibrance=intensity={vibrance}")
    ev = adjust.get("exposure_ev", 0.0)
    if ev:
        parts.append(f"exposure=exposure={ev}")
    eq = [f"{key}={adjust[src]}" for key, src in
          (("contrast", "contrast"), ("saturation", "saturation"), ("gamma", "gamma"))
          if adjust.get(src, 1.0) != 1.0]
    if eq:
        parts.append("eq=" + ":".join(eq))
    return ",".join(parts)


def build_finish_chain(color_cfg: dict) -> str:
    """Acabamento pós-scale: nitidez (unsharp só no luma) + grain (noise só no
    luma, temporal). Roda DEPOIS do resize da plataforma — quantidades são
    calibradas para a resolução de saída, não a da câmera."""
    finish = color_cfg.get("finish", {})
    parts = []
    sharpen = finish.get("sharpen", 0.0)
    if sharpen:
        parts.append(f"unsharp=5:5:{sharpen}:5:5:0")
    grain = finish.get("grain", 0)
    if grain:
        parts.append(f"noise=c0s={grain}:c0f=t")
    return ",".join(parts)


def build_audio_chain(audio_cfg: dict, measured: dict | None) -> str:
    """Cadeia de áudio a partir do style: loudnorm (+ segunda passada se houver
    medição) -> aresample -> hard limiter de segurança.

    Duas passadas de loudnorm porque a passada única é imprecisa no loudness
    integrado; com linear=true a segunda passada aplica ganho linear (sem
    bombear a dinâmica da fala). O alimiter no fim só apara picos inter-sample
    que sobrarem do encode.
    """
    ln = (f"loudnorm=I={audio_cfg['target_i']}:TP={audio_cfg['target_tp']}"
          f":LRA={audio_cfg['target_lra']}")
    if measured is None:
        return ln + ":print_format=json"
    ln += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
           f":measured_LRA={measured['input_lra']}"
           f":measured_thresh={measured['input_thresh']}"
           f":offset={measured['target_offset']}:linear=true")
    chain = [ln, "aresample=48000"]
    limiter = audio_cfg.get("limiter", {})
    if limiter.get("enabled"):
        limit_lin = 10 ** (limiter.get("limit_db", -1.5) / 20)
        # level=disabled é obrigatório: o default do alimiter re-normaliza a
        # saída para 0dB depois de limitar, desfazendo teto e loudness
        chain.append(f"alimiter=limit={limit_lin:.4f}"
                     f":attack={limiter.get('attack_ms', 5)}"
                     f":release={limiter.get('release_ms', 100)}"
                     f":level=disabled")
    return ",".join(chain)


def parse_loudnorm_json(stderr: str) -> dict:
    """Extrai o bloco JSON que o loudnorm imprime no fim do stderr."""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end < start:
        sys.exit(f"loudnorm não imprimiu medição:\n{stderr[-800:]}")
    return json.loads(stderr[start:end + 1])


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


def vertical_filter(src_w: int, src_h: int, platform: dict, x_offset: int) -> str:
    """Crop central (com offset) para o aspecto alvo + scale para a resolução alvo."""
    target_w, target_h = platform["width"], platform["height"]
    crop_w = round(src_h * target_w / target_h)
    x = (src_w - crop_w) // 2 + x_offset
    x = max(0, min(x, src_w - crop_w))
    return f"crop={crop_w}:{src_h}:{x}:0,scale={target_w}:{target_h}"


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
