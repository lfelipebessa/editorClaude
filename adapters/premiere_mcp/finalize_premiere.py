"""Finalização do fluxo do canal — roda inteira ou por etapa.

Fluxo padrão: compose_premiere --somente-corte monta a timeline só com
câmera + voz (V1 vazia — Close Gap funciona nativamente); o usuário faz os
ajustes manuais no corte; ESTE comando lê o corte FINAL da timeline e sobe o
resto já sincronizado a ele:

  V1  motions pré-fatiados nos cortes ATUAIS da câmera, âncoras de cena
      re-resolvidas pela fala remapeada (mesmo manifest da etapa 1)
  A*  música aparada ao fim real do conteúdo (track vazia, overwriteClip)
  C1  caption track do áudio atual (texto corrigido preservado do SRT)

--etapa fatia a finalização na ordem da metodologia do canal
(corte -> motions -> cor -> legendas), com checkpoint do usuário entre elas:

  --etapa motions   sobe motions + música e PARA (usuário revisa dinamismo,
                    aplica a cor manual por Paste Attributes da referência)
  --etapa legendas  legendas do estado ATUAL da timeline — sempre por último,
                    para absorver qualquer retoque feito nas etapas anteriores
  --etapa tudo      comportamento clássico, tudo de uma vez (padrão)

Uso (Premiere aberto, bridge ativa, timeline editada):
    python adapters/premiere_mcp/finalize_premiere.py \
        output/transcript_<slug>.json output/motion_manifest_<slug>.json \
        --sequence-name reel_<slug> [--etapa motions|legendas|tudo] \
        [--corrected-srt output/captions_<slug>.srt] \
        [--media-name dji_] [--camera-track 1] [--style seco]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_premiere import (add_music, build_mg_clips, build_position_y_jsx,
                              import_item)
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, find_key, load_style)

from render_ffmpeg import FFPROBE, resolve_music_file  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from compose import (find_scene_starts, format_srt, group_captions,
                     merge_corrected_text, parse_srt, remap_words_by_clips)
from cut_artifacts import (infer_speed_rate, segments_from_clips,
                           write_cut_artifacts)


def read_camera_clips(client: MCPStdioClient, track_index: int,
                      media_name: str) -> list[dict]:
    result = client.call_tool("execute_extendscript", {"script": f"""
      var seq = app.project.activeSequence;
      if (!seq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      var track = seq.videoTracks[{track_index}];
      var clips = [];
      for (var i = 0; i < track.clips.numItems; i++) {{
        var c = track.clips[i];
        if (String(c.name).indexOf("{media_name}") === -1) continue;
        clips.push({{start: c.start.seconds,
                     inPoint: c.inPoint.seconds,
                     outPoint: c.outPoint.seconds,
                     end: c.end.seconds}});
      }}
      return JSON.stringify({{success: true, clips: clips}});
    """})
    clips = result.get("clips") or []
    if not clips:
        raise MCPError(f"nenhum clipe de câmera com nome {media_name!r} "
                       f"na track V{track_index + 1}")
    return sorted(clips, key=lambda c: c["start"])


def apply_punch_in(client: MCPStdioClient, seq_id: str, punch_cfg: dict,
                   camera_track: int) -> None:
    """Punch-ins do canal (padrão desde 2026-08-04; `count` desde 2026-08-06):
    o 1º é o de abertura — clipe inicial da câmera E do motion abrem com zoom
    extra assentando rápido, blur só na câmera. Os `count - 1` extras caem SÓ
    na câmera, no corte cujo início fica mais perto de i/count da duração do
    conteúdo (mesmo tratamento pico -> base + blur) — dinamismo distribuído,
    não em todo corte. Única exceção autorizada à regra 'motion entra como
    autorado' é o punch de abertura. Keyframes ancoram no tempo da MÍDIA
    (inPoint + offset) — keyframe antes do inPoint cai na parte aparada do
    clipe e não renderiza nada."""
    zoom = punch_cfg.get("zoom", 1.2)
    scale_abs = punch_cfg.get("scale_abs")
    dur = punch_cfg.get("duration", 0.4)
    blur = punch_cfg.get("blur_amount", 8)
    blur_dur = punch_cfg.get("blur_duration", 0.25)
    count = max(1, int(punch_cfg.get("count", 1)))

    st = client.call_tool("get_sequence_structure", {"sequenceId": str(seq_id)})
    tracks = find_key(st, "videoTracks") or []

    def clips_da(track_index: int) -> list[dict]:
        if track_index >= len(tracks):
            return []
        clips = tracks[track_index].get("clips") or []
        return sorted(clips, key=lambda c: c.get("start", 0))

    cam = clips_da(camera_track)
    mot = clips_da(0)
    alvos: list[tuple[dict, bool]] = []
    if cam:
        alvos.append((cam[0], True))
    if mot:
        alvos.append((mot[0], False))
    if cam and count > 1:
        fim = cam[-1].get("end", 0)
        usados = {cam[0]["nodeId"]}
        # clipe mais curto que 2x o assentamento não segura um punch
        candidatos = [c for c in cam[1:]
                      if c.get("end", 0) - c.get("start", 0) >= dur * 2]
        for i in range(1, count):
            livres = [c for c in candidatos if c["nodeId"] not in usados]
            if not livres:
                break
            alvo_t = fim * i / count
            escolhido = min(livres,
                            key=lambda c: abs(c.get("start", 0) - alvo_t))
            usados.add(escolhido["nodeId"])
            print(f"  punch-in extra no corte de {escolhido.get('start', 0):.1f}s")
            alvos.append((escolhido, True))

    for clip, com_blur in alvos:
        if not clip:
            continue
        node_id = clip["nodeId"]
        props = client.call_tool("get_clip_properties", {"clipId": node_id})
        base = find_key(props, "scale") or 100
        in_pt = clip.get("inPoint", 0)
        # pico absoluto (scale_abs) vale para qualquer base — câmera 58 e
        # motion 100 abrem no MESMO Scale; sem scale_abs, multiplicador zoom
        pico = scale_abs if scale_abs else base * zoom
        delta = pico - base
        if delta <= 0:
            continue
        # assentamento rápido: pico -> 14.5% do delta aos 62.5% do tempo -> base
        for off, val in ((0.0, base + delta),
                         (dur * 0.625, base + delta * 0.145),
                         (dur, base)):
            client.call_tool("add_keyframe", {
                "clipId": node_id, "componentName": "Motion",
                "paramName": "Scale", "time": round(in_pt + off, 4),
                "value": round(val, 2)})
        if com_blur and blur > 0:
            client.call_tool("apply_effect", {"clipId": node_id,
                                              "effectName": "Gaussian Blur"})
            for off, val in ((0.0, blur), (blur_dur, 0)):
                client.call_tool("add_keyframe", {
                    "clipId": node_id, "componentName": "Gaussian Blur",
                    "paramName": "Amount", "time": round(in_pt + off, 4),
                    "value": val})


def media_duration(path: Path) -> float:
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise MCPError(f"ffprobe falhou em {path.name} (clipe corrompido/incompleto?): {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--corrected-srt", type=Path, default=None)
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--style", default="seco")
    parser.add_argument("--music", default=None)
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--etapa", choices=["tudo", "motions", "legendas"],
                        default="tudo")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    do_motions = args.etapa in ("tudo", "motions")
    do_captions = args.etapa in ("tudo", "legendas")

    for p in (args.transcript, args.manifest):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    transcript = json.loads(args.transcript.read_text())
    manifest = json.loads(args.manifest.read_text())
    layout = manifest.get("layout", {})
    scenes = manifest["scenes"]
    if do_motions:
        for sc in scenes:
            if not Path(sc["clip"]).exists():
                sys.exit(f"clipe de motion não encontrado: {sc['clip']}")
    style = load_style(args.style)

    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]
    if args.corrected_srt and args.corrected_srt.exists():
        words = merge_corrected_text(words,
                                     parse_srt(args.corrected_srt.read_text()))
        print(f"texto corrigido preservado de {args.corrected_srt.name}")

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
        total = round(max(c["end"] for c in clips), 3)
        print(f"corte final lido: {len(clips)} clipes, conteúdo até {total}s")

        out_words = remap_words_by_clips(words, clips)
        if not out_words:
            raise MCPError("nenhuma palavra caiu nos clipes — media-name certo?")

        # o corte ATUAL da timeline vira artefato — mantém transcript_cut fresco
        # a cada etapa (o usuário pode ter retocado o corte entre etapas)
        slug = args.sequence_name.removeprefix("reel_")
        rate = infer_speed_rate(
            transcript, style.get("speed", {}).get("rate", 1.2))
        p_cut, p_tr = write_cut_artifacts(
            transcript, segments_from_clips(clips), "timeline", slug, rate,
            words=words)
        print(f"artefatos do corte atualizados: {p_cut.name}, {p_tr.name}")

        feito = []
        if do_motions:
            starts = find_scene_starts(scenes, out_words)
            for sc, st in zip(scenes, starts):
                sc["start"] = st

            for i, sc in enumerate(scenes):
                span = ((scenes[i + 1]["start"] if i + 1 < len(scenes)
                         else total) - sc["start"])
                dur = media_duration(Path(sc["clip"]))
                if span > dur + 0.05:
                    modo = ("marcado como loop, mas o caminho Premiere NÃO "
                            "faz loop — repetir o clipe à mão"
                            if sc.get("loop") else "sem loop")
                    print(f"    AVISO: seção de {span:.2f}s > motion de "
                          f"{dur:.2f}s ({Path(sc['clip']).name}, {modo})")

            # V1 (abaixo da câmera) precisa estar vazia — é a etapa 1 que garante
            mg_track = 0
            st_struct = client.call_tool("get_sequence_structure",
                                         {"sequenceId": str(seq_id)})
            v1 = (find_key(st_struct, "videoTracks") or [{}])[mg_track]
            if v1.get("clips"):
                raise MCPError("V1 não está vazia — motions já subiram? "
                               "(a etapa motions roda uma vez só)")

            print("importando motions...")
            mg_ids = [import_item(client, Path(sc["clip"])) for sc in scenes]
            cam_starts = [c["start"] for c in clips[1:]]
            motion_y = layout.get("motion_y_px")
            mg_clips = build_mg_clips(scenes, mg_ids, cam_starts, total,
                                      y_px=motion_y,
                                      seq_h=layout.get("height", 1920))
            print(f"V1: {len(mg_clips)} pedaços de motion nos cortes atuais...")
            result = client.call_tool("add_to_timeline_batch",
                                      {"sequenceId": str(seq_id),
                                       "clips": mg_clips})
            if find_key(result, "status") == "failure":
                raise MCPError(f"batch de motions falhou: {result}")
            if motion_y is not None:
                client.call_tool("execute_extendscript",
                                 {"script": build_position_y_jsx(
                                     mg_track,
                                     motion_y / layout.get("height", 1920))})
            feito.append(f"{len(mg_clips)} motions")

            punch_cfg = style.get("punch_in")
            if punch_cfg:
                n_punch = max(1, int(punch_cfg.get("count", 1)))
                print(f"punch-ins: abertura (câmera + motion)"
                      f"{f' + {n_punch - 1} distribuídos' if n_punch > 1 else ''}...")
                apply_punch_in(client, str(seq_id), punch_cfg,
                               args.camera_track)
                feito.append("punch-in")

            music_cfg = style.get("music")
            if music_cfg and not args.no_music:
                music_file = resolve_music_file(music_cfg, args.music)
                add_music(client, str(seq_id), music_file, music_cfg, total)
                feito.append("música")

        if do_captions:
            cap_cfg = style.get("captions", {})
            chunks = group_captions(out_words,
                                    max_words=cap_cfg.get("max_words", 3),
                                    max_gap=cap_cfg.get("max_gap", 0.6))
            if cap_cfg.get("uppercase", True):
                for c in chunks:
                    c["text"] = c["text"].upper()
            out_srt = Path(f"output/captions_{args.sequence_name}_final.srt")
            out_srt.write_text(format_srt(chunks))
            srt_id = import_item(client, out_srt)
            client.call_tool("create_caption_track",
                             {"sequenceId": str(seq_id), "projectItemId": srt_id})
            print(f"caption track criada ({len(chunks)} legendas, SRT: {out_srt})")
            feito.append(f"{len(chunks)} legendas")

        client.call_tool("save_project", {})
        print(f"ETAPA {args.etapa.upper()}: {' + '.join(feito)} sobre o corte "
              f"de {len(clips)} clipes. Projeto salvo.")
        if do_motions and not do_captions:
            print("PRÓXIMO: revisar o dinamismo dos motions; cor = Paste "
                  "Attributes da referência em V2 (NUNCA Motion/Crop); depois "
                  "rodar de novo com --etapa legendas.")
        if do_captions:
            print("MANUAL: aplicar Track Style 'canal' na caption track; travar "
                  "a track da música; cor fina = Paste Attributes da referência.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
