"""Gera o handoff de motions a partir do corte APROVADO — o passo novo entre
o checkpoint de corte e a geração no MotionSkills (spec 2026-08-04).

Uso:
    python src/prepare_motion_handoff.py output/transcript_<slug>.json \
        --copy "/caminho/da/nota-de-copy.md" \
        --sequence-name reel_<slug> [--media-name dji_] [--camera-track 1]
    # fallback sem Premiere aberto (reflete o corte AUTOMÁTICO):
    python src/prepare_motion_handoff.py output/transcript_<slug>.json \
        --copy "..." --cutlist output/cutlist_<slug>.json

Saída: output/handoff_<slug>.md — blocos com tempo real do corte + texto
mesclado com a copy (grafia dela, conteúdo do falado) + TELA: reancorados +
seção Divergências. Enviar ao Produtor de Video do MotionSkills via Maestri.
"""

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_ROOT / "adapters"))  # render_ffmpeg (import indireto)
sys.path.insert(0, str(_ROOT / "adapters" / "premiere_mcp"))

from compose import remap_words, remap_words_by_clips
from motion_handoff import (anchor_telas, assign_words, build_blocks,
                            divergent_blocks, format_handoff,
                            merge_with_copy, parse_copy)


def read_timeline_bounds(sequence_name: str, camera_track: int,
                         media_name: str, timeout: float) -> list[dict]:
    """Clipes de câmera da timeline (posição real pós-edição manual)."""
    from finalize_premiere import read_camera_clips
    from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY,
                                 MCPStdioClient)
    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=timeout)
    client.start()
    try:
        seqs = client.call_tool("list_sequences", {})
        seq_id = next((s["id"] for s in seqs.get("sequences", [])
                       if s.get("name") == sequence_name), None)
        if not seq_id:
            sys.exit(f"sequência {sequence_name!r} não encontrada")
        client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})
        return read_camera_clips(client, camera_track, media_name)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--copy", type=Path, default=None,
                        help="nota de copy no vault (markdown)")
    parser.add_argument("--sequence-name", default=None,
                        help="lê o corte REAL da timeline (padrão do fluxo)")
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--cutlist", type=Path, default=None,
                        help="fallback sem Premiere: corte automático")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-block", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not args.sequence_name and not args.cutlist:
        sys.exit("informe --sequence-name (timeline) ou --cutlist (fallback)")
    if not args.transcript.exists():
        sys.exit(f"não encontrado: {args.transcript}")

    slug = args.transcript.stem.replace("transcript_", "")
    out_path = args.out or Path(f"output/handoff_{slug}.md")

    transcript = json.loads(args.transcript.read_text())
    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]

    if args.sequence_name:
        clips = read_timeline_bounds(args.sequence_name, args.camera_track,
                                     args.media_name, args.timeout)
        out_words = remap_words_by_clips(words, clips)
        bounds = [(round(c["start"], 3), round(c["end"], 3)) for c in clips]
    else:
        if not args.cutlist.exists():
            sys.exit(f"não encontrado: {args.cutlist}")
        print("AVISO: handoff a partir da CUTLIST — reflete o corte "
              "automático, não o ajuste manual da timeline.")
        cutlist = json.loads(args.cutlist.read_text())
        out_words = remap_words(words, cutlist["segments"])
        bounds, off = [], 0.0
        for s in cutlist["segments"]:
            dur = s["end"] - s["start"]
            bounds.append((round(off, 3), round(off + dur, 3)))
            off += dur
    if not out_words:
        sys.exit("nenhuma palavra sobreviveu ao remap — "
                 "transcript e corte batem?")

    chunks, telas, copy_ref = [], [], None
    if args.copy and args.copy.exists():
        chunks, telas = parse_copy(args.copy.read_text())
        copy_ref = args.copy.stem
    else:
        origem = f"copy não encontrada ({args.copy})" if args.copy \
            else "sem --copy"
        print(f"AVISO: {origem} — texto 100% ASR, REVISAR grafia de marcas "
              "no handoff antes do envio.")

    merged = merge_with_copy(out_words, chunks)
    blocks = build_blocks(bounds, min_dur=args.min_block)
    assign_words(blocks, merged)
    anchor_telas(telas, merged, blocks)
    out_path.write_text(format_handoff(slug, blocks, copy_ref))

    div = divergent_blocks(blocks)
    total = blocks[-1]["end"] if blocks else 0.0
    print(f"handoff: {out_path} ({len(blocks)} blocos, {total:.1f}s, "
          f"{len(telas)} TELA, {len(div)} divergentes)")
    if div:
        print("divergências marcadas no arquivo — envio segue automático, "
              "relatório vai junto para o produtor.")


if __name__ == "__main__":
    main()
