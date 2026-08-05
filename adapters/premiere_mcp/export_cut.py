"""Fecha o CHECKPOINT 1: lê o corte FINAL da timeline e persiste os artefatos.

Rodar quando o usuário fechar a edição manual do corte (Premiere aberto, painel
MCP Bridge ativo). Grava cutlist_final_<slug>.json + transcript_cut_<slug>.json
em output/. Depois disso o diff de copy, o re-render ffmpeg e o fallback do
handoff (prepare_motion_handoff) funcionam SEM Premiere.

Uso:
    python adapters/premiere_mcp/export_cut.py output/transcript_<slug>.json \
        --sequence-name reel_<slug> [--media-name dji_] [--camera-track 1] \
        [--slug <slug>] [--style seco]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, load_style)
from finalize_premiere import read_camera_clips

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from cut_artifacts import (infer_speed_rate, segments_from_clips,
                           write_cut_artifacts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--slug", default=None)
    parser.add_argument("--style", default="seco")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not args.transcript.exists():
        sys.exit(f"não encontrado: {args.transcript}")
    transcript = json.loads(args.transcript.read_text())
    slug = args.slug or args.sequence_name.removeprefix("reel_")

    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=args.timeout)
    client.start()
    try:
        seqs = client.call_tool("list_sequences", {})
        seq_id = next((s["id"] for s in seqs.get("sequences", [])
                       if s.get("name") == args.sequence_name), None)
        if not seq_id:
            raise MCPError(f"sequência {args.sequence_name!r} não encontrada")
        client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})
        clips = read_camera_clips(client, args.camera_track, args.media_name)
    finally:
        client.close()

    rate = infer_speed_rate(
        transcript, load_style(args.style).get("speed", {}).get("rate", 1.2))
    p_cut, p_tr = write_cut_artifacts(transcript, segments_from_clips(clips),
                                      "timeline", slug, rate)
    tcut = json.loads(p_tr.read_text())
    print(f"CHECKPOINT 1 persistido: {len(clips)} clipes, "
          f"corte de {tcut['cut_duration']}s (origem: timeline)")
    print(f"  {p_cut}\n  {p_tr}")
    print("PRÓXIMO: gerar o handoff pro MotionSkills "
          "(src/prepare_motion_handoff.py — plano motion-checkpoint).")


if __name__ == "__main__":
    main()
