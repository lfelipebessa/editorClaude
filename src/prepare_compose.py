"""Gera motion-manifest + SRT a partir dos artefatos do vídeo — a cola que
torna o composer 100% automático: transcript + cutlist + brief do MotionSkills
+ pasta de clips entram, manifest resolvido e legendas editáveis saem.

Uso:
    python src/prepare_compose.py output/transcript_<slug>.json \
        output/cutlist_<slug>.json <dir do vídeo no MotionSkills> \
        [--out-manifest output/motion_manifest_<slug>.json] \
        [--out-srt output/captions_<slug>.srt] [--style seco]

O <dir> é o do vídeo no MotionSkills (ex.: .../src/videos/plugin-administrativo,
que tem o brief.md); os clips são procurados em out/<nome-do-dir>/clips/.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from core.transcript import (find_scene_starts, format_srt, group_captions,
                     parse_brief_scenes, remap_words)

from core import load_style


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("motions_dir", type=Path,
                        help="dir do vídeo no MotionSkills (contém brief.md)")
    parser.add_argument("--out-manifest", type=Path, default=None)
    parser.add_argument("--out-srt", type=Path, default=None)
    parser.add_argument("--style", default="seco")
    parser.add_argument("--motion-y-px", type=int, default=None,
                        help="LEGADO — não usar. Padrão do canal (2026-07-31): motion entra "
                             "exatamente como autorado, sem ajuste de posição/altura/zoom. "
                             "A flag só existe para reprocessar sets antigos.")
    args = parser.parse_args()

    brief = args.motions_dir / "brief.md"
    for p in (args.transcript, args.cutlist, brief):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    clips_dir = (args.motions_dir.parent.parent.parent / "out"
                 / args.motions_dir.name / "clips")
    if not clips_dir.is_dir():
        sys.exit(f"clips renderizados não encontrados: {clips_dir}\n"
                 f"renderize no MotionSkills antes (npx remotion render).")

    slug = args.cutlist.stem.replace("cutlist_", "")
    out_manifest = args.out_manifest or Path(f"output/motion_manifest_{slug}.json")
    out_srt = args.out_srt or Path(f"output/captions_{slug}.srt")

    transcript = json.loads(args.transcript.read_text())
    cutlist = json.loads(args.cutlist.read_text())
    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]
    out_words = remap_words(words, cutlist["segments"])
    if not out_words:
        sys.exit("nenhuma palavra sobreviveu ao remap — cutlist/transcript batem?")

    scenes = parse_brief_scenes(brief.read_text())
    if not scenes:
        sys.exit(f"nenhuma cena na tabela do brief: {brief}")
    for sc in scenes:
        matches = sorted(clips_dir.glob(f"{sc['num']}-*.mp4"))
        if not matches:
            sys.exit(f"clip da cena {sc['num']} não encontrado em {clips_dir}")
        sc["clip"] = str(matches[0])

    starts = find_scene_starts(scenes, out_words)
    for sc, st in zip(scenes, starts):
        sc["start"] = st
    manifest = {"version": 1,
                "layout": {"motion": "top", "camera": "bottom",
                           "width": 1080, "height": 1920, "fps": 30,
                           **({"motion_y_px": args.motion_y_px}
                              if args.motion_y_px else {})},
                "cutlist": str(args.cutlist),
                "scenes": [{"clip": sc["clip"], "match": sc["match"],
                            "loop": sc["loop"], "start": sc["start"]}
                           for sc in scenes]}
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    cap_cfg = load_style(args.style).get("captions", {})
    chunks = group_captions(out_words,
                            max_words=cap_cfg.get("max_words", 3),
                            max_gap=cap_cfg.get("max_gap", 0.6))
    if cap_cfg.get("uppercase", True):
        for c in chunks:
            c["text"] = c["text"].upper()
    if cap_cfg.get("strip_punctuation", True):
        # legenda de rede social não leva ponto final/exclamação; "?" e
        # reticências ficam (pergunta é rara mas existe).
        for c in chunks:
            c["text"] = re.sub(r"(?<!\.)\.(?=\s|$)|!(?=\s|$)", "", c["text"])
    out_srt.write_text(format_srt(chunks))

    total = round(sum(s["end"] - s["start"] for s in cutlist["segments"]), 1)
    print(f"manifest: {out_manifest} ({len(scenes)} cenas sobre {total}s)")
    for i, sc in enumerate(scenes):
        end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        secao = end - sc["start"]
        print(f"  {Path(sc['clip']).name:20s} t={sc['start']:6.2f}s "
              f"secao={secao:5.2f}s loop={sc['loop']}")
        if sc.get("dur") is not None and abs(secao - sc["dur"]) > 0.5:
            print(f"    AVISO: brief declara {sc['dur']}s, seção real tem "
                  f"{secao:.2f}s — motion será truncado ou vai sobrar "
                  f"(brief autorado sobre fala divergente? gerar do handoff "
                  f"do corte aprovado)")
    print(f"srt: {out_srt} ({len(chunks)} legendas, "
          f"{'MAIÚSCULAS' if cap_cfg.get('uppercase', True) else 'como faladas'})")
    print("IMPORTANTE: revisar o SRT contra o brief antes do render — "
          "transcrição erra palavra (ex.: cloud->Claude).")


if __name__ == "__main__":
    main()
