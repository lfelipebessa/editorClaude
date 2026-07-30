"""Refaz as legendas com base no estado ATUAL da timeline no Premiere.

Depois de edição manual (cortes, encurtamentos), a caption track original
dessincroniza. Este comando lê os clipes de voz da timeline (posição + trecho
do bruto que usam), reposiciona as palavras do WhisperX por esse layout,
preserva o TEXTO já corrigido do SRT anterior (alinhamento por token) e cria
uma caption track nova. Nenhuma re-transcrição.

Uso (Premiere aberto, bridge ativa):
    python adapters/premiere_mcp/recaption_premiere.py \
        output/transcript_<slug>.json --sequence-name reel_<slug> \
        [--corrected-srt output/captions_<slug>.srt] [--style seco] \
        [--media-name <trecho do nome do arquivo da câmera>]

Pós-execução (manual, limites da API): apagar a(s) caption track(s) antiga(s)
e aplicar o Track Style `canal` na nova.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_premiere import import_item
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, load_style)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from compose import (format_srt, group_captions, merge_corrected_text,
                     parse_srt, remap_words_by_clips)


def read_voice_clips(client: MCPStdioClient, media_name: str) -> list[dict]:
    """Clipes de voz da sequência ativa: posição na timeline + in/out no bruto.
    Procura em TODAS as tracks de áudio pelos clipes do arquivo da câmera."""
    result = client.call_tool("execute_extendscript", {"script": f"""
      var seq = app.project.activeSequence;
      if (!seq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      var clips = [];
      for (var t = 0; t < seq.audioTracks.numTracks; t++) {{
        var track = seq.audioTracks[t];
        for (var i = 0; i < track.clips.numItems; i++) {{
          var c = track.clips[i];
          if (String(c.name).indexOf("{media_name}") === -1) continue;
          clips.push({{start: c.start.seconds,
                       inPoint: c.inPoint.seconds,
                       outPoint: c.outPoint.seconds}});
        }}
      }}
      return JSON.stringify({{success: true, clips: clips}});
    """})
    clips = result.get("clips") or []
    if not clips:
        raise MCPError(f"nenhum clipe de voz com nome contendo {media_name!r}")
    return clips


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--corrected-srt", type=Path, default=None,
                        help="SRT com texto já corrigido — o texto dele é "
                             "preservado por alinhamento")
    parser.add_argument("--media-name", default="dji_",
                        help="trecho do nome do arquivo da câmera na timeline")
    parser.add_argument("--style", default="seco")
    parser.add_argument("--out-srt", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    if not args.transcript.exists():
        sys.exit(f"não encontrado: {args.transcript}")
    transcript = json.loads(args.transcript.read_text())
    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]
    if args.corrected_srt and args.corrected_srt.exists():
        corrected = parse_srt(args.corrected_srt.read_text())
        words = merge_corrected_text(words, corrected)
        print(f"texto corrigido preservado de {args.corrected_srt.name}")

    out_srt = args.out_srt or Path(
        f"output/captions_{args.sequence_name}_recut.srt")

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
        client.call_tool("set_active_sequence", {"sequenceId": seq_id})

        clips = read_voice_clips(client, args.media_name)
        print(f"{len(clips)} clipes de voz lidos da timeline atual")
        out_words = remap_words_by_clips(words, clips)
        if not out_words:
            raise MCPError("nenhuma palavra caiu nos clipes — media-name certo?")

        cap_cfg = load_style(args.style).get("captions", {})
        chunks = group_captions(out_words,
                                max_words=cap_cfg.get("max_words", 3),
                                max_gap=cap_cfg.get("max_gap", 0.6))
        if cap_cfg.get("uppercase", True):
            for c in chunks:
                c["text"] = c["text"].upper()
        out_srt.write_text(format_srt(chunks))
        print(f"SRT novo: {out_srt} ({len(chunks)} legendas)")

        srt_id = import_item(client, out_srt)
        client.call_tool("create_caption_track",
                         {"sequenceId": str(seq_id), "projectItemId": srt_id})
        client.call_tool("save_project", {})
        print("caption track nova criada e projeto salvo.")
        print("MANUAL: apagar a(s) track(s) de legenda antiga(s) e aplicar o "
              "Track Style 'canal' na nova.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
