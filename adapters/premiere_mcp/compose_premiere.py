"""Composer vertical no Premiere: monta o Reel como TIMELINE EDITÁVEL.

Consome os MESMOS contratos do composer ffmpeg (cut-list + motion-manifest +
SRT) e entrega a estrutura que o usuário finaliza na mão:

  V1  motions full-frame nos tempos resolvidos (fundo sangra atrás da câmera)
  V2  cortes da câmera escalados/posicionados na metade de baixo (Motion
      editável clipe a clipe)
  C1  caption track criada do SRT — texto corrigível no painel de Captions

Cor NÃO entra por script (fluxo do canal): Paste Attributes da sequência de
referência nos clipes de V2, marcando só Lumetri Color e Noise (Motion NÃO,
senão perde o enquadramento). Áudio segue o da câmera, sem normalização — o
render final editável é do usuário; o mp4 automático usa o composer ffmpeg.

Uso (Premiere aberto com painel MCP Bridge iniciado, projeto já aberto):
    python adapters/premiere_mcp/compose_premiere.py <video> <cutlist.json> \
        <manifest.json> --srt <legendas.srt> [--sequence-name reel] [--timeout 120]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, build_batch, find_key)


def camera_transform(src_w: int, src_h: int, seq_w: int,
                     seq_h: int) -> tuple[float, list[float]]:
    """Scale (%) e Position (normalizada) para a câmera preencher a metade de
    baixo da sequência: altura vira seq_h/2, largura sobra e é cortada pelo
    quadro (crop central implícito)."""
    scale = round(seq_h / 2 / src_h * 100, 2)
    return scale, [0.5, 0.75]


def build_motion_jsx(track_index: int, scale: float,
                     position: list[float]) -> str:
    """ExtendScript: seta Motion Scale/Position de TODOS os clipes da track
    em uma chamada (Position é normalizada 0-1 no DOM do Premiere)."""
    pos = json.dumps(position)
    return f"""
      var seq = app.project.activeSequence;
      if (!seq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      var track = seq.videoTracks[{track_index}];
      var done = 0;
      for (var c = 0; c < track.clips.numItems; c++) {{
        var clip = track.clips[c];
        for (var k = 0; k < clip.components.numItems; k++) {{
          if (String(clip.components[k].displayName) !== "Motion") continue;
          var comp = clip.components[k];
          for (var j = 0; j < comp.properties.numItems; j++) {{
            var p = comp.properties[j];
            try {{
              if (p.displayName === "Scale") p.setValue({scale}, true);
              if (p.displayName === "Position") p.setValue({pos}, true);
            }} catch (e) {{}}
          }}
          done++;
          break;
        }}
      }}
      return JSON.stringify({{success: true, clips: done}});
    """


def import_item(client: MCPStdioClient, path: Path) -> str:
    imported = client.call_tool("import_media", {"filePath": str(path.resolve())})
    item_id = find_key(imported, "projectItemId", "itemId", "nodeId", "id")
    if not item_id:
        raise MCPError(f"import de {path.name} não retornou id")
    return str(item_id)


def compose(video: Path, cutlist: dict, manifest: dict, srt: Path | None,
            sequence_name: str, timeout: float) -> None:
    segments = cutlist["segments"]
    total = round(sum(s["end"] - s["start"] for s in segments), 3)
    scenes = manifest["scenes"]
    layout = manifest.get("layout", {})
    seq_w, seq_h = layout.get("width", 1080), layout.get("height", 1920)

    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=timeout)
    client.start()
    try:
        info = client.call_tool("get_project_info", {})
        print(f"projeto aberto: {info.get('name')}")

        print("importando mídia (câmera + motions + srt)...")
        cam_id = import_item(client, video)
        mg_ids = [import_item(client, Path(sc["clip"])) for sc in scenes]
        srt_id = import_item(client, srt) if srt else None

        # sequência vertical sem diálogo modal: nasce de um clipe de motion
        # (1080x1920 @30fps) e vira uma duplicata vazia — mesma dança validada
        # do render_premiere (create_sequence abriria o diálogo New Sequence).
        print(f"criando sequência {sequence_name} ({seq_w}x{seq_h})...")
        tmp = client.call_tool("create_sequence_from_clips",
                               {"name": f"{sequence_name}_tmp",
                                "projectItemIds": [mg_ids[0]]})
        tmp_id = find_key(tmp, "sequenceId", "sequenceID")
        if not tmp_id:
            raise MCPError("create_sequence_from_clips não retornou sequenceId")
        seq = client.call_tool("duplicate_sequence",
                               {"sequenceId": str(tmp_id),
                                "newName": sequence_name,
                                "clearContents": True})
        seq_id = find_key(seq, "sequenceId", "sequenceID")
        if not seq_id:
            seqs = client.call_tool("list_sequences", {})
            for s in seqs.get("sequences", []):
                if s.get("name") == sequence_name and not s.get("duration"):
                    seq_id = s.get("id")
                    break
        if not seq_id:
            raise MCPError("duplicate_sequence não retornou sequenceId")
        client.call_tool("delete_sequence", {"sequenceId": str(tmp_id)})
        client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})

        # V1: motions nos tempos resolvidos do manifest (full-frame)
        mg_clips = []
        for sc, mg_id in zip(scenes, mg_ids):
            i = scenes.index(sc)
            end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
            mg_clips.append({"projectItemId": mg_id, "trackIndex": 0,
                             "time": round(sc["start"], 3),
                             "sourceInPoint": 0,
                             "sourceOutPoint": round(end - sc["start"], 3)})
        print(f"V1: {len(mg_clips)} motions...")
        result = client.call_tool("add_to_timeline_batch",
                                  {"sequenceId": str(seq_id), "clips": mg_clips})
        if find_key(result, "status") == "failure":
            raise MCPError(f"batch de motions falhou: {result}")

        # V2: cortes da câmera
        tracks = client.call_tool("get_track_info", {"sequenceId": str(seq_id)})
        n_video = len([t for t in find_key(tracks, "videoTracks") or []]) or 1
        if n_video < 2:
            client.call_tool("add_track", {"sequenceId": str(seq_id),
                                           "trackType": "video"})
        cam_clips = build_batch(cutlist, cam_id)
        for c in cam_clips:
            c["trackIndex"] = 1
        print(f"V2: {len(cam_clips)} cortes de câmera...")
        result = client.call_tool("add_to_timeline_batch",
                                  {"sequenceId": str(seq_id), "clips": cam_clips})
        if find_key(result, "status") == "failure":
            raise MCPError(f"batch da câmera falhou: {result}")

        # Motion da câmera: metade de baixo
        video_info = client.call_tool("get_project_item_info",
                                      {"projectItemId": cam_id})
        src_w = find_key(video_info, "width") or 3840
        src_h = find_key(video_info, "height") or 2160
        scale, position = camera_transform(int(src_w), int(src_h), seq_w, seq_h)
        print(f"posicionando câmera (scale {scale}%, pos {position})...")
        moved = client.call_tool("execute_extendscript",
                                 {"script": build_motion_jsx(1, scale, position)})
        if moved.get("clips") != len(cam_clips):
            raise MCPError(f"Motion aplicado em {moved.get('clips')} de "
                           f"{len(cam_clips)} clipes")

        if srt_id:
            print("criando caption track do SRT...")
            client.call_tool("create_caption_track",
                             {"sequenceId": str(seq_id),
                              "projectItemId": srt_id})

        client.call_tool("save_project", {})
        print(f"sequência '{sequence_name}' montada: {len(mg_clips)} motions + "
              f"{len(cam_clips)} cortes + captions (~{total:.1f}s). Projeto salvo.")
        print("Lembrete: cor = Paste Attributes da referência em V2 "
              "(Lumetri Color + Noise; NUNCA marcar Motion).")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--srt", type=Path, default=None)
    parser.add_argument("--sequence-name", default="reel_composto")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    for p in (args.video, args.cutlist, args.manifest):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    if args.srt and not args.srt.exists():
        sys.exit(f"SRT não encontrado: {args.srt}")
    cutlist = json.loads(args.cutlist.read_text())
    manifest = json.loads(args.manifest.read_text())
    for sc in manifest["scenes"]:
        if not Path(sc["clip"]).exists():
            sys.exit(f"clipe de motion não encontrado: {sc['clip']}")

    compose(args.video, cutlist, manifest, args.srt, args.sequence_name,
            args.timeout)


if __name__ == "__main__":
    main()
