"""Composer vertical ffmpeg (Fase 3): bruto 4K + cut-list + motion-manifest ->
Reel 1080x1920 em UM encode. Motion em cima (metade split-safe), câmera embaixo
(crop 9:8 gradado), legendas na divisa queimadas a partir do SRT editável.

Spec: note "01-spec-vertical-composer" (Maestri). Decisões: compor a 30fps
(nativo dos motions; câmera 23.976->30 é imperceptível em talking head);
cor SÓ na câmera (scope: camera); finish (sharpen+grain) no quadro inteiro;
áudio 100% da câmera com loudnorm 2-pass + limiter do style.

Uso:
    python adapters/compose_ffmpeg.py <video> <cutlist.json> <manifest.json> \
        [-o out.mp4] [--style seco] [--srt legendas.srt] [--crop-x-offset px] \
        [--no-color]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from math import ceil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from render_ffmpeg import (FFMPEG, build_audio_chain, build_color_chain,
                           build_filter, build_finish_chain, build_music_chain,
                           load_style, measure_loudness, measure_music_loudness,
                           pick_streams, probe_resolution, resolve_music_file)

from compose import parse_srt


def build_mg_track(scenes: list[dict], total: float,
                   fps: int = 30) -> tuple[str, list[list[str]]]:
    """Trilha de motion: cada cena vira o trecho [start_i, start_{i+1}) do
    corte. Hold-safe: trim -> tpad clone -> trim garante duração exata mesmo
    se o clipe for mais curto que a seção (congela o último frame). Cena com
    loop=true entra com -stream_loop -1 (o trim corta no fim da seção).
    Corta a metade de CIMA do frame do motion (1080x960) — o conteúdo
    split-safe do MotionSkills mora em y 90-910.
    """
    lines, labels, input_flags = [], [], []
    for i, sc in enumerate(scenes):
        end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        dur = round(end - sc["start"], 3)
        lines.append(
            f"[{i + 1}:v]trim=duration={dur},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={dur},trim=duration={dur},"
            f"fps={fps},crop=1080:960:0:0,setsar=1[mg{i}];")
        labels.append(f"[mg{i}]")
        input_flags.append(["-stream_loop", "-1"] if sc.get("loop") else [])
    lines.append("".join(labels) + f"concat=n={len(scenes)}:v=1:a=0[mg]")
    return "\n".join(lines), input_flags


def build_camera_branch(src_w: int, src_h: int, x_offset: int,
                        color_chain: str, fps: int = 30) -> str:
    """Câmera: cor (se houver) -> crop central 9:8 (com offset) -> 1080x960."""
    crop_w = round(src_h * 9 / 8)
    x = (src_w - crop_w) // 2 + x_offset
    x = max(0, min(x, src_w - crop_w))
    parts = [color_chain] if color_chain else []
    parts.append(f"crop={crop_w}:{src_h}:{x}:0")
    parts.append(f"scale=1080:960,fps={fps},setsar=1")
    return ",".join(parts)


DEFAULT_CAPTION_FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"


def _wrap_caption(text: str, probe, font, stroke: int, max_w: int) -> str:
    """Quebra em 2 linhas balanceadas quando o bloco não cabe em max_w —
    com fonte grande, blocos de 3 palavras podem passar de 1080."""
    def width(t):
        box = probe.textbbox((0, 0), t, font=font, stroke_width=stroke)
        return box[2] - box[0]
    words = text.split()
    if len(words) < 2 or width(text) <= max_w:
        return text
    splits = ((max(width(" ".join(words[:i])), width(" ".join(words[i:]))),
               " ".join(words[:i]) + "\n" + " ".join(words[i:]))
              for i in range(1, len(words)))
    return min(splits)[1]


def render_caption_images(chunks: list[dict], cfg: dict,
                          out_dir: Path) -> list[Path]:
    """Cada legenda vira um PNG transparente (Pillow) — o ffmpeg desta máquina
    não tem libass/drawtext, e PNG dá controle tipográfico total. O SRT segue
    sendo a fonte editável: mudou o texto, os PNGs regeneram no re-render."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(cfg.get("font_file", DEFAULT_CAPTION_FONT),
                              cfg.get("size", 64))
    stroke = cfg.get("outline", 4)
    max_w = cfg.get("max_width", 1040)
    pad = stroke + 8
    paths = []
    for i, c in enumerate(chunks):
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        text = _wrap_caption(c["text"], probe, font, stroke, max_w)
        box = probe.textbbox((0, 0), text, font=font, stroke_width=stroke,
                             align="center")
        # textbbox multilinha retorna floats; Image.new exige ints
        img = Image.new("RGBA", (ceil(box[2] - box[0]) + 2 * pad,
                                 ceil(box[3] - box[1]) + 2 * pad), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((pad - box[0], pad - box[1]), text, font=font,
                  fill="white", stroke_width=stroke, stroke_fill="black",
                  align="center")
        path = out_dir / f"cap{i:03d}.png"
        img.save(path)
        paths.append(path)
    return paths


def build_caption_overlays(chunks: list[dict], first_idx: int,
                           y: int = 976) -> tuple[str, str]:
    """Cadeia de overlays: cada PNG aparece só na janela [start, end] da sua
    legenda, apoiado na divisa motion/câmera — a borda inferior do PNG fica em
    y, então o texto senta sobre a linha da divisa (fundo escuro do motion),
    só encostando nela por baixo. Vírgulas do between() escapadas — separador
    de filtro no graph script."""
    lines, label = [], "[stack]"
    for i, c in enumerate(chunks):
        out = f"[cap{i}]"
        lines.append(
            f"{label}[{first_idx + i}:v]overlay=(W-w)/2:{y}-h:"
            f"eof_action=pass:enable=between(t\\,{c['start']}\\,{c['end']})"
            f"{out};")
        label = out
    return "\n".join(lines)[:-1], label


def compose(video: Path, cutlist: dict, manifest: dict, output: Path,
            style: dict, srt: Path | None, x_offset: int,
            no_color: bool, music_file: Path | None = None) -> None:
    segments = cutlist["segments"]
    total = round(sum(s["end"] - s["start"] for s in segments), 3)
    scenes = manifest["scenes"]
    fps = manifest.get("layout", {}).get("fps", 30)

    video_idx, audio_idx = pick_streams(video)
    if audio_idx is None:
        sys.exit("vídeo sem áudio — composer exige a fala da câmera")
    src_w, src_h = probe_resolution(video, video_idx)

    color_cfg = style.get("color") or {}
    color_chain = "" if no_color else build_color_chain(color_cfg)
    finish_chain = "" if no_color else build_finish_chain(color_cfg)

    graph = [build_filter(segments, video_idx, audio_idx)]
    graph.append(f"[v]{build_camera_branch(src_w, src_h, x_offset, color_chain, fps)}[cam]")
    mg_graph, input_flags = build_mg_track(scenes, total, fps)
    graph.append(mg_graph)
    graph.append("[mg][cam]vstack=inputs=2[stack]")

    label = "[stack]"
    cap_paths: list[Path] = []
    if srt:
        chunks = parse_srt(srt.read_text())
        cap_dir = Path(tempfile.mkdtemp(prefix="editorclaude_captions_"))
        cap_paths = render_caption_images(chunks, style.get("captions", {}),
                                          cap_dir)
        overlays, label = build_caption_overlays(chunks, 1 + len(scenes))
        graph.append(overlays)
    if finish_chain:
        graph.append(f"{label}{finish_chain}[vout]")
        label = "[vout]"

    print("medindo loudness do corte (passada 1)...")
    measured = measure_loudness(video, segments, audio_idx, style["audio"])
    graph.append(f"[a]{build_audio_chain(style['audio'], measured)}[af]")
    map_audio = "[af]"
    if music_file:
        music_i = measure_music_loudness(music_file)
        music_idx = 1 + len(scenes) + len(cap_paths)
        graph.append(f"[{music_idx}:a]"
                     f"{build_music_chain(style['music'], total, music_i)}[mus]")
        graph.append("[af][mus]amix=inputs=2:duration=first:normalize=0[aout]")
        map_audio = "[aout]"
        print(f"música de fundo: {music_file.name} ({music_i} LUFS -> bed)")

    filter_graph = ";\n".join(graph)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(filter_graph)
        script = f.name

    cmd = [FFMPEG, "-y", "-i", str(video)]
    for sc, flags in zip(scenes, input_flags):
        cmd += [*flags, "-i", sc["clip"]]
    for path in cap_paths:
        cmd += ["-loop", "1", "-t", str(total), "-i", str(path)]
    if music_file:
        # sem stream_loop: com start_offset o loop repetiria a intro pulada;
        # música mais curta que o vídeo só termina antes (aviso no console)
        cmd += ["-i", str(music_file)]
    cmd += ["-filter_complex_script", script,
            "-map", label, "-map", map_audio,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output)]
    print(f"compondo {len(scenes)} cenas + câmera + legendas ({total:.1f}s)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(script).unlink(missing_ok=True)
    if result.returncode != 0:
        sys.exit(f"ffmpeg falhou:\n{result.stderr[-2000:]}")
    print(f"composto: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("-o", "--output", type=Path,
                        default=Path("output/composed.mp4"))
    parser.add_argument("--style", default="seco")
    parser.add_argument("--srt", type=Path, default=None,
                        help="SRT editável para queimar na divisa (opcional)")
    parser.add_argument("--crop-x-offset", type=int, default=0)
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--music", default=None,
                        help="música da biblioteca assets/music (nome sem "
                             "extensão) ou caminho; default = a do style")
    parser.add_argument("--no-music", action="store_true")
    args = parser.parse_args()

    for p in (args.video, args.cutlist, args.manifest):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    cutlist = json.loads(args.cutlist.read_text())
    manifest = json.loads(args.manifest.read_text())
    for sc in manifest["scenes"]:
        if not Path(sc["clip"]).exists():
            sys.exit(f"clipe de motion não encontrado: {sc['clip']}")
    if args.srt and not args.srt.exists():
        sys.exit(f"SRT não encontrado: {args.srt}")

    style = load_style(args.style)
    music_file = None
    if not args.no_music and style.get("music"):
        music_file = resolve_music_file(style["music"], args.music)
    compose(args.video, cutlist, manifest, args.output, style,
            args.srt, args.crop_x_offset, args.no_color, music_file)


if __name__ == "__main__":
    main()
