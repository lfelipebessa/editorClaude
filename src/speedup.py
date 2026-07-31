"""Acelera o vídeo bruto na taxa padrão do canal (seção `speed` do style).

PASSO ZERO do fluxo de Reel falado: a aceleração acontece ANTES da transcrição,
porque transcript, cut-list, âncoras de motion e legendas referenciam timestamps
do arquivo fonte — acelerar depois quebraria todos os mapeamentos. Todo o
pipeline downstream roda sobre o arquivo acelerado sem mudar uma linha.

Pitch preservado (atempo), fps mantido (setpts), CRF 18 para a grade de cor
não herdar artefato de compressão.

Uso:
    python src/speedup.py <video> [-o saida.mp4] [--rate 1.2] [--style seco]
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutlist import load_style

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def load_speed_rate(style_name: str) -> float:
    return float(load_style(style_name).get("speed", {}).get("rate", 1.0))


def default_output(video: Path, rate: float) -> Path:
    tag = f"{rate:g}".replace(".", "")  # 1.2 -> "12x"
    return video.with_name(f"{video.stem}_{tag}x.mp4")


def speedup(video: Path, output: Path, rate: float) -> None:
    if not 1.0 < rate <= 2.0:
        sys.exit(f"rate {rate} fora da faixa sã (1.0–2.0]; atempo aceita, "
                 f"mas fala acima de 2x vira ruído")
    subprocess.run(
        [FFMPEG, "-y", "-i", str(video),
         "-filter_complex",
         f"[0:v]setpts=PTS/{rate}[v];[0:a]atempo={rate}[a]",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart", str(output)],
        check=True, capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="padrão: <video>_12x.mp4 ao lado do fonte")
    parser.add_argument("--rate", type=float, default=None,
                        help="sobrepõe a taxa do style")
    parser.add_argument("--style", default="seco")
    args = parser.parse_args()

    if not args.video.exists():
        sys.exit(f"vídeo não encontrado: {args.video}")
    rate = args.rate if args.rate is not None else load_speed_rate(args.style)
    if rate == 1.0:
        sys.exit(f"style {args.style!r} sem seção speed e --rate não passado — "
                 f"nada a fazer")
    output = args.output or default_output(args.video, rate)
    if output.exists():
        sys.exit(f"{output} já existe — não sobrescrevo mídia; apague antes "
                 f"se quiser regerar")

    speedup(args.video, output, rate)
    print(f"acelerado {rate:g}x: {output}")
    print(f"daqui em diante o fluxo inteiro usa {output.name} como fonte "
          f"(transcrição, corte, compose)")


if __name__ == "__main__":
    main()
