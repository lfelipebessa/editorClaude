"""Cadeias de filtro do ffmpeg montadas a partir do style.

Só monta string de filtergraph — não chama ffmpeg. Quem executa é o core.media
e os adaptadores. Manter assim deixa tudo aqui testável sem vídeo nenhum.
"""

import sys
from pathlib import Path

from core.style import PROJECT_ROOT


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


def music_gain_db(music_cfg: dict, measured_i: float) -> float:
    """Ganho (dB) para a música cair no nível de bed do style. As músicas do
    canal variam ~6 dB entre si — o ganho é calculado da medição, nunca fixo."""
    return round(music_cfg.get("bed_lufs", -36.0) - measured_i, 2)


def build_music_chain(music_cfg: dict, total: float, measured_i: float) -> str:
    """Cadeia da música de fundo (aplicada ao input próprio da música; o input
    entra com -stream_loop -1 -t <total>: loopa se curta, corta se longa).
    Mix final: amix com duration=first e normalize=0 (o bed não pode mexer no
    nível da voz já normalizada)."""
    parts = []
    offset = music_cfg.get("start_offset", 0)
    if offset:
        # pula a intro lenta e entra no refrão (padrão do canal)
        parts += [f"atrim=start={offset}", "asetpts=PTS-STARTPTS"]
    parts += [f"volume={music_gain_db(music_cfg, measured_i)}dB",
              "aresample=48000"]
    fade = music_cfg.get("fade_out", 1.5)
    if fade:
        parts.append(f"afade=t=out:st={round(max(0.0, total - fade), 3)}:d={fade}")
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
