"""Composer vertical "tela + rosto": gravação de tela em cima, câmera embaixo —
o formato de corte de vídeo de YouTube (screencast + webcam) para Reels.

Diferente do compose_ffmpeg (motion em cima), aqui a metade de cima é a própria
gravação de tela. As duas metades saem dos canais BRUTOS de dentro do bundle
.screenstudio, nunca do export renderizado:

- TELA: `channel-1-display-*` (3420x2214). O export do Screen Studio traz zoom
  por clique e a bolha da webcam colada no canto inferior direito — o zoom
  empurra o conteúdo justamente para debaixo da bolha, então não dá para
  recortar a tela do export sem perder metade do que importa. Do bruto eu
  escolho o enquadramento, e o downscale 3420->1080 deixa o texto nítido.
- ROSTO: `channel-3-webcam-*` (1920x1080), e não a bolha do export — a bolha
  tem ~490px e subiria 2.2x para preencher a metade de baixo (borrado).

O bundle grava em SESSÕES (cada pausa abre uma nova) e o export é a
concatenação delas. Toda a receita fala no relógio do EXPORT (que é o do
transcript); cada sessão entra com o `offset` dela dentro dele, medido por
correlação de envelope de áudio (src/sync_screenstudio.py), nunca chutado.

O áudio vem do export inteiro — é o único relógio contínuo, e é o mesmo em que
o transcript foi feito.

Uso:
    python adapters/reel_screencam.py <receita.json> -o ~/Downloads/reel.mp4
    python adapters/reel_screencam.py <receita.json> --contact-sheet folha.jpg

Receita (JSON): ver output/reel_deploy_1608.json. Campos:
    audio            mp4 com o áudio contínuo (o export)
    top / bottom     {"sessions": [{"file","offset"}], "crop": {w,h,x,y}}
    top_h            altura da metade de cima (padrão 960 = divisa no meio)
    speed            aceleração final (1.2 = padrão do canal para Reel)
    segments         [{"start","end","label", "top_crop"?, "cam_crop"?}]
                     — os crops por segmento sobrescrevem os globais.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core import (FFMPEG, FFPROBE, build_audio_chain,
                           build_music_chain, load_style, measure_loudness,
                           measure_music_loudness, resolve_music_file)

OUT_W, OUT_H = 1080, 1920
FPS = 30


def probe_duration(path: str) -> float:
    """Duração da sessão. HLS não reporta em format=duration; cai no pacote."""
    for entries in ("format=duration", "stream=duration"):
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", entries,
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout.strip()
        val = out.splitlines()[0].strip().rstrip(",") if out else ""
        if val and val != "N/A":
            return float(val)
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets,avg_frame_rate",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip().split(",")
    num, den = out[1].split("/")
    return int(out[0]) / (int(num) / int(den))


def pick_session(sessions: list[dict], t: float) -> tuple[dict, float]:
    """Sessão que cobre o instante `t` do export + o tempo local dentro dela.

    De trás para frente: as sessões se sobrepõem por algumas dezenas de ms na
    emenda, e quem manda ali é a que ESTÁ COMEÇANDO — a anterior só tem um
    rabicho de frames antes de acabar.
    """
    for s in reversed(sessions):
        local = t - s["offset"]
        if -0.001 <= local < s["duration"]:
            return s, max(0.0, local)
    sys.exit(f"nenhuma sessão cobre t={t:.2f}s do export")


def crop_str(c: dict) -> str:
    return f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}"


def half_chain(label_in: str, crop: dict, w: int, h: int, out: str) -> str:
    """setpts+fps ANTES do resto: a captura de tela é VFR (r=60, avg=47) e sem
    isso o vídeo corre na frente do áudio, pior a cada segundo."""
    return (f"[{label_in}]setpts=PTS-STARTPTS,fps={FPS},{crop_str(crop)},"
            f"scale={w}:{h},setsar=1[{out}];")


def segment_filter(top_crop: dict, cam_crop: dict, top_h: int) -> str:
    bot_h = OUT_H - top_h
    return (half_chain("0:v", top_crop, OUT_W, top_h, "top")
            + half_chain("1:v", cam_crop, OUT_W, bot_h, "bot")
            + "[top][bot]vstack=inputs=2[v]")


def seg_sources(rec: dict, seg: dict, t: float) -> tuple[dict, float, dict, float]:
    """Fontes de tela e de rosto para o instante `t` do segmento.

    `top_at` na receita destrava a tela como B-ROLL: o rosto e o áudio ficam
    onde estão, mas a metade de cima vai buscar OUTRO ponto da gravação. Serve
    para o gancho — a fala que vende o resultado quase nunca acontece enquanto
    o resultado está na tela.
    """
    top_t = t + (seg["top_at"] - seg["start"]) if "top_at" in seg else t
    top, t_local = pick_session(rec["top"]["sessions"], top_t)
    bot, b_local = pick_session(rec["bottom"]["sessions"], t)
    return top, t_local, bot, b_local


def seg_crops(rec: dict, seg: dict) -> tuple[dict, dict]:
    return (seg.get("top_crop", rec["top"]["crop"]),
            seg.get("cam_crop", rec["bottom"]["crop"]))


def render_segment(rec: dict, seg: dict, out: Path) -> None:
    start, end = seg["start"], seg["end"]
    dur = round(end - start, 3)
    top, t_local, bot, b_local = seg_sources(rec, seg, start)
    for src, local, name in ((top, t_local, "tela"), (bot, b_local, "câmera")):
        if local + dur > src["duration"] + 0.05:
            sys.exit(f"segmento {start:.2f}-{end:.2f} atravessa o fim da sessão "
                     f"de {name}: {src['file']} — quebre o corte na borda")
    top_crop, cam_crop = seg_crops(rec, seg)
    cmd = [
        FFMPEG, "-v", "error", "-y",
        "-ss", f"{t_local:.3f}", "-t", f"{dur:.3f}", "-i", top["file"],
        "-ss", f"{b_local:.3f}", "-t", f"{dur:.3f}", "-i", bot["file"],
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", rec["audio"],
        "-filter_complex", segment_filter(top_crop, cam_crop,
                                          rec.get("top_h", 960)),
        "-map", "[v]", "-map", "2:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def contact_sheet(rec: dict, out: Path, at: str = "mid") -> None:
    """1 frame composto por segmento numa folha de contato — valida
    enquadramento de tela E de rosto antes de gastar o render inteiro."""
    work = Path(tempfile.mkdtemp(prefix="screencam_sheet_"))
    stills = []
    for i, seg in enumerate(rec["segments"]):
        t = {"start": seg["start"] + 0.2, "mid": (seg["start"] + seg["end"]) / 2,
             "end": seg["end"] - 0.2}[at]
        top, t_local, bot, b_local = seg_sources(rec, seg, t)
        top_crop, cam_crop = seg_crops(rec, seg)
        still = work / f"s{i:02d}.jpg"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y",
             "-ss", f"{t_local:.3f}", "-i", top["file"],
             "-ss", f"{b_local:.3f}", "-i", bot["file"],
             "-filter_complex",
             segment_filter(top_crop, cam_crop, rec.get("top_h", 960))
             + ";[v]scale=360:640,drawbox=x=0:y=0:w=360:h=640:"
             + "color=yellow@0.9:t=3[o]",
             "-map", "[o]", "-frames:v", "1", "-update", "1", str(still)],
            check=True)
        stills.append(still)
    rows = [stills[i:i + 5] for i in range(0, len(stills), 5)]
    cmd = [FFMPEG, "-v", "error", "-y"]
    for s in stills:
        cmd += ["-i", str(s)]
    fg, idx, row_labels = [], 0, []
    for r, row in enumerate(rows):
        ins = "".join(f"[{idx + j}:v]" for j in range(len(row)))
        idx += len(row)
        fg.append(f"{ins}hstack=inputs={len(row)}[r{r}]" if len(row) > 1
                  else f"{ins}null[r{r}]")
        row_labels.append(f"[r{r}]")
    if len(rows) > 1:
        fg.append(f"{''.join(row_labels)}vstack=inputs={len(rows)}[o]")
    else:
        fg.append("[r0]null[o]")
    # linhas curtas ganham fundo preto para o vstack casar a largura
    widths = {len(r) for r in rows}
    if len(widths) > 1:
        fg = fg[:-1]
        pad = 360 * max(len(r) for r in rows)
        for r, row in enumerate(rows):
            fg.append(f"[r{r}]pad={pad}:640:0:0:black[p{r}]")
        fg.append(f"{''.join(f'[p{r}]' for r in range(len(rows)))}"
                  f"vstack=inputs={len(rows)}[o]")
    cmd += ["-filter_complex", ";".join(fg), "-map", "[o]", "-update", "1",
            str(out)]
    subprocess.run(cmd, check=True)
    print(f"folha de contato ({at}): {out}  ({len(stills)} segmentos)")


def finalize(rec: dict, concat_file: Path, out: Path, style: dict,
             music: str | None) -> None:
    """Velocidade do canal + loudnorm 2ª passada (+ música) num encode só."""
    speed = rec.get("speed", 1.0)
    seg_total = sum(s["end"] - s["start"] for s in rec["segments"])
    total = seg_total / speed

    measured = measure_loudness(Path(rec["audio"]), rec["segments"], 1,
                                style["audio"])
    achain = build_audio_chain(style["audio"], measured)

    vf = f"setpts=PTS/{speed}" if speed != 1.0 else "null"
    af = [f"atempo={speed}"] if speed != 1.0 else []
    af.append(achain)

    inputs = ["-f", "concat", "-safe", "0", "-i", str(concat_file)]
    lines = [f"[0:v]{vf}[v]", f"[0:a]{','.join(af)}[voz]"]
    amap = "[voz]"
    if music:
        mfile = resolve_music_file(style["music"], music)
        mi = measure_music_loudness(mfile)
        inputs += ["-stream_loop", "-1", "-i", str(mfile)]
        lines.append(f"[1:a]{build_music_chain(style['music'], total, mi)}[bed]")
        lines.append("[voz][bed]amix=inputs=2:duration=first:"
                     "dropout_transition=0:normalize=0[aout]")
        amap = "[aout]"
    cmd = [FFMPEG, "-v", "error", "-y", *inputs,
           "-filter_complex", ";".join(lines),
           "-map", "[v]", "-map", amap,
           "-c:v", "libx264", "-preset", "slow", "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def load_recipe(path: Path) -> dict:
    rec = json.loads(path.read_text())
    for side in ("top", "bottom"):
        for s in rec[side]["sessions"]:
            s["duration"] = probe_duration(s["file"])
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recipe", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--contact-sheet", type=Path)
    ap.add_argument("--sheet-at", default="mid",
                    choices=["start", "mid", "end"])
    ap.add_argument("--style", default="seco")
    ap.add_argument("--music", default=None)
    ap.add_argument("--no-music", action="store_true")
    args = ap.parse_args()

    rec = load_recipe(args.recipe)

    if args.contact_sheet:
        contact_sheet(rec, args.contact_sheet, args.sheet_at)
        return
    if not args.output:
        sys.exit("faltou -o/--output")

    style = load_style(args.style)
    work = Path(tempfile.mkdtemp(prefix="screencam_"))
    parts = []
    for i, seg in enumerate(rec["segments"]):
        part = work / f"seg{i:02d}.mp4"
        render_segment(rec, seg, part)
        parts.append(part)
        print(f"  seg {i:02d} {seg['start']:7.2f}-{seg['end']:7.2f}  "
              f"{seg.get('label', '')}")

    listfile = work / "concat.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in parts))
    finalize(rec, listfile, args.output, style,
             None if args.no_music else (args.music or style["music"]["default"]))

    seg_total = sum(s["end"] - s["start"] for s in rec["segments"])
    speed = rec.get("speed", 1.0)
    print(f"\n{args.output}")
    print(f"  {len(parts)} segmentos | fonte {seg_total:.1f}s | "
          f"{speed}x -> final {seg_total / speed:.1f}s")


if __name__ == "__main__":
    main()
