"""Composer vertical no Premiere: monta o Reel como TIMELINE EDITÁVEL.

Consome os MESMOS contratos do composer ffmpeg (cut-list + motion-manifest +
SRT) e entrega a estrutura que o usuário finaliza na mão:

  V1  motions full-frame nos tempos resolvidos (fundo sangra atrás da câmera)
  V2  cortes da câmera na metade de baixo com o enquadramento padrão do canal
      (zoom com a cabeça quase encostando na divisa + Crop Top devolvendo a
      divisa exata; Motion/Crop editáveis clipe a clipe)
  C1  caption track criada do SRT — texto corrigível no painel de Captions

Cor NÃO entra por script (fluxo do canal): Paste Attributes da sequência de
referência nos clipes de V2, marcando só Lumetri Color e Noise (Motion NÃO,
senão perde o enquadramento). Áudio segue o da câmera, sem normalização — o
render final editável é do usuário; o mp4 automático usa o composer ffmpeg.

Uso (Premiere aberto com painel MCP Bridge iniciado, projeto já aberto):
    python adapters/premiere_mcp/compose_premiere.py <video> <cutlist.json> \
        [<manifest.json>] --srt <legendas.srt> [--sequence-name reel] [--timeout 120]
No modo --somente-corte o manifest é dispensado (molde de formato é gerado
automaticamente).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit_camera import fit as fit_camera
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, build_batch, find_key)

from render_ffmpeg import (FFMPEG, FFPROBE, load_style,  # noqa: E402
                           measure_music_loudness, music_gain_db,
                           resolve_music_file)


# Enquadramento padrão do canal (selado pelo usuário em 2026-08-07, herdando o
# ajuste manual do reel_0508 publicado — antes: zoom 1.305/Scale 58 em 4K,
# aprovado 2026-07-30): zoom sobre o fill da metade de baixo com a cabeça quase
# encostando na divisa do motion. Assume o setup fixo do estúdio (câmera
# parada, rosto na região central) — conferir por frame exportado.
CAMERA_ZOOM = 1.4175
CAMERA_POSITION = [0.52, 0.6973]
# Fonte estreita (bruto já vertical, de celular): o zoom absoluto de estúdio
# não transfere — selfie já vem fechada no rosto. O que transfere é o aperto
# criativo do 0508 sobre o enquadramento antigo (63/58), por cima do width-fill.
CAMERA_TIGHTEN = round(1.4175 / 1.305, 4)


def camera_transform(src_w: int, src_h: int, seq_w: int,
                     seq_h: int) -> tuple[float, list[float], float]:
    """Scale (%), Position (normalizada) e Crop Top (%) da câmera na metade de
    baixo. O zoom faz o clipe subir acima da divisa (seq_h/2) para o rosto
    subir junto; o Crop Top corta o excesso e devolve a divisa exata — o corte
    vira transparência, então o motion de V1 continua aparecendo. Para fonte
    4K 16:9 em 1080x1920: Scale 63, Position [0.52, 0.6973], Crop Top 22.16.
    Fonte estreita (bruto já vertical, ex. 720x1280): o height-fill deixaria
    barras laterais — prevalece o width-fill vezes CAMERA_TIGHTEN, com X
    centralizado (selfie já centraliza o rosto; offset viraria barra)."""
    scale = round(seq_h / 2 / src_h * 100 * CAMERA_ZOOM, 2)
    position = list(CAMERA_POSITION)
    width_fill = round(seq_w / src_w * 100 * CAMERA_TIGHTEN, 2)
    if width_fill > scale:
        scale = width_fill
        position[0] = 0.5
    clip_h = src_h * scale / 100
    clip_top = position[1] * seq_h - clip_h / 2
    crop_top = round(max(0.0, (seq_h / 2 - clip_top) / clip_h * 100), 2)
    return scale, position, crop_top


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


def build_crop_jsx(track_index: int, top_pct: float) -> str:
    """ExtendScript: efeito Crop com Top (%) em TODOS os clipes da track, em
    uma chamada. Componentes sempre localizados por displayName — o Premiere 26
    pode inserir efeito novo antes dos existentes, nunca confiar na posição."""
    return f"""
      app.enableQE();
      var cropFx = qe.project.getVideoEffectByName("Crop");
      if (!cropFx) return JSON.stringify({{success: false, error: "efeito Crop indisponível"}});
      var seq = app.project.activeSequence;
      var qeSeq = qe.project.getActiveSequence();
      if (!seq || !qeSeq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      function findComp(domClip, name) {{
        for (var k = 0; k < domClip.components.numItems; k++) {{
          if (String(domClip.components[k].displayName) === name) return domClip.components[k];
        }}
        return null;
      }}
      var qeTrack = qeSeq.getVideoTrackAt({track_index});
      var domTrack = seq.videoTracks[{track_index}];
      var applied = 0, clipIdx = 0;
      for (var i = 0; i < qeTrack.numItems; i++) {{
        var item = qeTrack.getItemAt(i);
        var kind = "";
        try {{ kind = String(item.type); }} catch (e) {{}}
        if (kind !== "Clip") continue;
        var domClip = domTrack.clips[clipIdx];
        var comp = findComp(domClip, "Crop");
        if (!comp) {{
          item.addVideoEffect(cropFx);
          comp = findComp(domClip, "Crop");
        }}
        if (comp) {{
          var done = false;
          for (var j = 0; j < comp.properties.numItems; j++) {{
            var p = comp.properties[j];
            try {{
              if (!done && p.displayName === "Top") {{ p.setValue({top_pct}, true); done = true; }}
            }} catch (e2) {{}}
          }}
          applied++;
        }}
        clipIdx++;
      }}
      return JSON.stringify({{success: true, applied: applied}});
    """


def build_position_y_jsx(track_index: int, y_norm: float) -> str:
    """ExtendScript: seta SÓ o Position Y dos clipes da track (X e Scale
    intactos) — compensação de sets de motion autorados fora do split-safe."""
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
              if (p.displayName === "Position") {{
                var cur = p.getValue();
                p.setValue([cur[0], {y_norm}], true);
              }}
            }} catch (e) {{}}
          }}
          done++;
          break;
        }}
      }}
      return JSON.stringify({{success: true, clips: done}});
    """


def ensure_mold_clip(w: int, h: int, fps: int) -> Path:
    """Clipe preto de 1s usado só como molde de formato da sequência —
    create_sequence abriria o diálogo modal New Sequence, então a sequência
    precisa nascer de um clipe (dança validada do render_premiere). Gerado
    uma vez em output/ (gitignored). Gravação atômica (tmp + replace): um
    ffmpeg morto no meio nunca deixa o mold.mp4 final truncado, o que
    faria o cache `if not mold.exists()` engolir um arquivo corrompido."""
    w, h, fps = int(w), int(h), int(fps)
    mold = (Path(__file__).resolve().parent.parent.parent
            / "output" / f"mold_{w}x{h}_{fps}.mp4")
    if not mold.exists():
        mold.parent.mkdir(exist_ok=True)
        tmp = mold.with_suffix(".tmp.mp4")
        try:
            subprocess.run(
                [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r={fps}",
                 "-t", "1", "-pix_fmt", "yuv420p", str(tmp)], check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            sys.exit(f"ffmpeg falhou ao gerar o molde: {e}")
        tmp.replace(mold)
    return mold


def import_item(client: MCPStdioClient, path: Path) -> str:
    imported = client.call_tool("import_media", {"filePath": str(path.resolve())})
    item_id = find_key(imported, "projectItemId", "itemId", "nodeId", "id")
    if not item_id:
        raise MCPError(f"import de {path.name} não retornou id")
    return str(item_id)


def build_music_place_jsx(item_id: str, track_index: int, offset: float,
                          total: float) -> str:
    """ExtendScript que coloca a música numa track de áudio VAZIA via
    overwriteClip, com in/out no source (pula a intro).

    NUNCA usar add_to_timeline_batch para áudio: o trackIndex dele endereça o
    PAR vídeo+áudio e o overwrite APAGOU a voz do usuário em 2026-07-30
    (a track de destino era a A2, onde o áudio da câmera morava)."""
    return f"""
      var seq = app.project.activeSequence;
      if (!seq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      var item = null;
      function walk(bin) {{
        for (var i = 0; i < bin.children.numItems; i++) {{
          var ch = bin.children[i];
          if (String(ch.nodeId) === "{item_id}") {{ item = ch; return; }}
          if (ch.type === 2 && ch.children) walk(ch);
        }}
      }}
      walk(app.project.rootItem);
      if (!item) return JSON.stringify({{success: false, error: "item da música não achado"}});
      var track = seq.audioTracks[{track_index}];
      if (!track) return JSON.stringify({{success: false, error: "track {track_index} não existe"}});
      if (track.clips.numItems > 0)
        return JSON.stringify({{success: false, error: "track {track_index} não está vazia"}});
      item.setInPoint({offset}, 4);
      item.setOutPoint({round(offset + total, 3)}, 4);
      track.overwriteClip(item, 0);
      return JSON.stringify({{success: true, clips: track.clips.numItems}});
    """


def build_mg_clips(scenes: list[dict], mg_ids: list[str],
                   cam_starts: list[float], total: float,
                   y_px: int | None = None,
                   seq_h: int = 1920) -> list[dict]:
    """Motions para V1 JÁ CORTADOS nos pontos de corte da câmera.

    Com os cortes alinhados, apagar um trecho do rosto + o pedaço de motion
    acima e dar ripple delete fecha a timeline inteira mantendo o sync
    (com a track da música LOCKED). O conteúdo visual não muda: os pedaços
    são fatias contíguas do mesmo clipe de motion.
    """
    clips = []
    for i, (sc, mg_id) in enumerate(zip(scenes, mg_ids)):
        start = sc["start"]
        end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        bounds = ([round(start, 5)]
                  + [round(t, 5) for t in cam_starts if start < t < end]
                  + [round(end, 5)])
        for a, b in zip(bounds, bounds[1:]):
            clip = {"projectItemId": mg_id, "trackIndex": 0,
                    "time": a,
                    "sourceInPoint": round(a - start, 5),
                    "sourceOutPoint": round(b - start, 5)}
            if y_px is not None:
                # compensação para sets autorados fora do split-safe
                # (conteúdo acima de y=90); padrão é posição nativa
                clip["positionY"] = y_px / seq_h
            clips.append(clip)
    return clips


def add_music(client: MCPStdioClient, seq_id: str, music_file: Path,
              music_cfg: dict, total: float) -> float:
    """Música de fundo numa track de áudio VAZIA (procura a primeira livre;
    cria uma se não houver), com in/out pulando a intro (start_offset do
    style) e ganho calculado da medição (bed_lufs). Fade out fica manual —
    o ganho é o que importa para o padrão."""
    measured_i = measure_music_loudness(music_file)
    gain = music_gain_db(music_cfg, measured_i)
    offset = music_cfg.get("start_offset", 0)
    mus_id = import_item(client, music_file)

    st = client.call_tool("get_sequence_structure", {"sequenceId": str(seq_id)})
    audio_tracks = find_key(st, "audioTracks") or []
    empty = [t.get("index") for t in audio_tracks if not t.get("clips")]
    if empty:
        track_index = empty[0]
    else:
        client.call_tool("add_track", {"sequenceId": str(seq_id),
                                       "trackType": "audio"})
        track_index = len(audio_tracks)

    placed = client.call_tool("execute_extendscript",
                              {"script": build_music_place_jsx(
                                  mus_id, track_index, offset, total)})
    if placed.get("clips") != 1:
        raise MCPError(f"colocar música falhou: {placed}")

    st = client.call_tool("get_sequence_structure", {"sequenceId": str(seq_id)})
    clip_id = None
    for track in find_key(st, "audioTracks") or []:
        if track.get("index") == track_index:
            clips = track.get("clips", [])
            if clips:
                clip_id = clips[0].get("nodeId") or clips[0].get("clipId")
    if not clip_id:
        raise MCPError("clipe da música não localizado após colocar")
    client.call_tool("adjust_audio_levels", {"clipId": str(clip_id),
                                             "level": gain})
    print(f"música: {music_file.name} (A{track_index + 1}, pulando {offset}s "
          f"de intro, {measured_i} LUFS, ganho {gain} dB)")
    return gain


def compose(video: Path, cutlist: dict, manifest: dict, srt: Path | None,
            sequence_name: str, timeout: float,
            music_file: Path | None = None,
            music_cfg: dict | None = None,
            somente_corte: bool = False,
            ajustar_por_clipe: bool = True) -> None:
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

        if somente_corte:
            # etapa 1: só câmera + voz; um clipe-molde preto dá o formato da
            # sequência (1080x1920 @30) — clips de motion ainda não existem,
            # nascem do corte aprovado (spec 2026-08-04).
            print("importando mídia (etapa CORTE: câmera + molde de formato)...")
            cam_id = import_item(client, video)
            mg_ids = [import_item(client, ensure_mold_clip(
                seq_w, seq_h, layout.get("fps", 30)))]
            srt_id = None
        else:
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

        # V1: motions nos tempos resolvidos, PRÉ-CORTADOS nos cortes da câmera
        cam_clips = build_batch(cutlist, cam_id, fps=layout.get("fps", 30))
        if not somente_corte:
            cam_starts = [c["time"] for c in cam_clips[1:]]
            motion_y = layout.get("motion_y_px")
            mg_clips = build_mg_clips(scenes, mg_ids, cam_starts, total,
                                      y_px=motion_y, seq_h=seq_h)
            print(f"V1: {len(mg_clips)} pedaços de motion (cortes alinhados à câmera)...")
            result = client.call_tool("add_to_timeline_batch",
                                      {"sequenceId": str(seq_id), "clips": mg_clips})
            if find_key(result, "status") == "failure":
                raise MCPError(f"batch de motions falhou: {result}")
            if motion_y is not None:
                client.call_tool("execute_extendscript",
                                 {"script": build_position_y_jsx(0, motion_y / seq_h)})
                print(f"motions compensados para y={motion_y}px (set fora do split-safe)")
        else:
            mg_clips = []

        # V2: cortes da câmera
        tracks = client.call_tool("get_track_info", {"sequenceId": str(seq_id)})
        n_video = len([t for t in find_key(tracks, "videoTracks") or []]) or 1
        if n_video < 2:
            client.call_tool("add_track", {"sequenceId": str(seq_id),
                                           "trackType": "video"})
        for c in cam_clips:
            c["trackIndex"] = 1
        print(f"V2: {len(cam_clips)} cortes de câmera...")
        result = client.call_tool("add_to_timeline_batch",
                                  {"sequenceId": str(seq_id), "clips": cam_clips})
        if find_key(result, "status") == "failure":
            raise MCPError(f"batch da câmera falhou: {result}")

        # Motion da câmera: metade de baixo. Dimensões via ffprobe do arquivo —
        # o get_project_item_info nem sempre traz width/height (mp4 de celular)
        # e o antigo fallback 4K aplicava Scale 58 em fonte 720x1280.
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True).stdout.strip()
        src_w, src_h = (int(v) for v in probe.split(",")[:2])
        scale, position, crop_top = camera_transform(int(src_w), int(src_h),
                                                     seq_w, seq_h)
        print(f"posicionando câmera (scale {scale}%, pos {position}, "
              f"crop top {crop_top}%)...")
        moved = client.call_tool("execute_extendscript",
                                 {"script": build_motion_jsx(1, scale, position)})
        if moved.get("clips") != len(cam_clips):
            raise MCPError(f"Motion aplicado em {moved.get('clips')} de "
                           f"{len(cam_clips)} clipes")
        if crop_top:
            cropped = client.call_tool("execute_extendscript",
                                       {"script": build_crop_jsx(1, crop_top)})
            if cropped.get("applied") != len(cam_clips):
                raise MCPError(f"Crop aplicado em {cropped.get('applied')} de "
                               f"{len(cam_clips)} clipes")

        # ajuste fino POR CLIPE: o transform acima é o padrão do canal, mas com
        # a câmera na mão a cabeça sobe e desce ao longo da gravação e um único
        # Position Y erra em metade dos clipes (3 rodadas de retrabalho no
        # reel_0708). Mede a cabeça em cada clipe e resolve individualmente.
        if ajustar_por_clipe:
            try:
                fit_camera(video, sequence_name, track_index=1,
                           media_name=video.stem[:12], client=client)
            except (MCPError, subprocess.CalledProcessError, OSError) as e:
                print(f"  AVISO: ajuste por clipe falhou ({e}) — "
                      f"transform global mantido; conferir por frame exportado")

        if srt_id:
            print("criando caption track do SRT...")
            client.call_tool("create_caption_track",
                             {"sequenceId": str(seq_id),
                              "projectItemId": srt_id})

        if music_file and music_cfg and not somente_corte:
            add_music(client, str(seq_id), music_file, music_cfg, total)

        client.call_tool("save_project", {})
        if somente_corte:
            print(f"etapa CORTE pronta: '{sequence_name}' só com câmera + voz "
                  f"({len(cam_clips)} cortes). Edite à vontade (Close Gap "
                  f"funciona — V1 vazia); quando fechar o corte, rode "
                  f"finalize_premiere.py para subir motions + música + legendas.")
            return
        print(f"sequência '{sequence_name}' montada: {len(mg_clips)} motions + "
              f"{len(cam_clips)} cortes + captions (~{total:.1f}s). Projeto salvo.")
        print("Lembrete: cor = Paste Attributes da referência em V2 "
              "(Lumetri Color + Noise; NUNCA marcar Motion nem Crop, "
              "senão perde o enquadramento).")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("manifest", type=Path, nargs="?", default=None,
                        help="opcional com --somente-corte (clips ainda não existem)")
    parser.add_argument("--srt", type=Path, default=None)
    parser.add_argument("--sequence-name", default="reel_composto")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--style", default="seco")
    parser.add_argument("--music", default=None,
                        help="música da biblioteca assets/music (nome sem "
                             "extensão) ou caminho; default = a do style")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--sem-ajuste-por-clipe", action="store_true",
                        help="não medir a cabeça clipe a clipe; usa só o "
                             "transform global do canal (câmera travada em tripé)")
    parser.add_argument("--somente-corte", action="store_true",
                        help="etapa 1 do fluxo do canal: só câmera + voz; "
                             "motions/legenda/música sobem depois via "
                             "finalize_premiere.py, sincronizados ao corte final")
    args = parser.parse_args()

    if args.manifest is None and not args.somente_corte:
        sys.exit("manifest é obrigatório fora de --somente-corte")
    for p in (args.video, args.cutlist) + \
            ((args.manifest,) if args.manifest else ()):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    if args.srt and not args.srt.exists():
        sys.exit(f"SRT não encontrado: {args.srt}")
    cutlist = json.loads(args.cutlist.read_text())
    manifest = (json.loads(args.manifest.read_text()) if args.manifest
                else {"scenes": [], "layout": {}})
    if not args.somente_corte:
        for sc in manifest["scenes"]:
            if not Path(sc["clip"]).exists():
                sys.exit(f"clipe de motion não encontrado: {sc['clip']}")

    music_cfg = load_style(args.style).get("music")
    music_file = None
    if not args.no_music and music_cfg:
        music_file = resolve_music_file(music_cfg, args.music)

    compose(args.video, cutlist, manifest, args.srt, args.sequence_name,
            args.timeout, music_file, music_cfg, args.somente_corte,
            not args.sem_ajuste_por_clipe)


if __name__ == "__main__":
    main()
