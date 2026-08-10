"""Enquadra a câmera clipe a clipe pela posição real da cabeça.

Por que existe: com o celular na mão (ou qualquer setup não travado) o
enquadramento varia ao longo da gravação. Um único Position Y para a sequência
inteira — calculado pelo pior caso ou por um frame só — deixa a cabeça colada na
divisa num clipe e com folga demais noutro. Em 2026-08-10 isso custou três
rodadas de ajuste manual no reel_0708 antes de fechar.

O que faz: mede o topo da cabeça em 3 frames de CADA clipe (pixels escuros no
terço horizontal central), toma o pior caso do clipe, e resolve Position Y +
Crop Top para aquela cabeça ficar `margin` px abaixo da divisa do motion,
mantendo a borda de baixo exatamente na divisa.

Uso (Premiere aberto, bridge ativa):
    python adapters/premiere_mcp/fit_camera.py <video> --sequence-name reel_<slug>
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, find_key)

DEFAULT_MARGIN = 22      # px entre o topo da cabeça e a divisa (padrão do canal)
SAMPLES = (0.25, 0.5, 0.75)   # frações do clipe amostradas
DARK_SUM = 180           # soma RGB abaixo disso conta como cabelo/escuro
MIN_DARK_PIXELS = 20     # pixels escuros na linha para valer como topo da cabeça


def head_top(video: Path, t: float, tmp: Path) -> int | None:
    """Linha (y no source) do topo da cabeça no instante t, ou None."""
    from PIL import Image
    frame = tmp / "probe.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}",
                    "-i", str(video), "-frames:v", "1", str(frame)],
                   check=True, capture_output=True)
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    px = img.load()
    for y in range(h):
        escuros = sum(1 for x in range(w // 3, 2 * w // 3)
                      if sum(px[x, y]) < DARK_SUM)
        if escuros > MIN_DARK_PIXELS:
            return y
    return None


def solve(head_y: int, src_h: int, scale_pct: float, seq_h: int,
          margin: int) -> tuple[float, float]:
    """Position Y normalizada e Crop Top (%) para a cabeça ficar margin px
    abaixo da divisa (seq_h / 2), com a borda de baixo na divisa."""
    f = scale_pct / 100
    pos_y = round((seq_h / 2 + margin - (head_y - src_h / 2) * f) / seq_h, 4)
    clip_h = src_h * f
    crop_top = round((seq_h / 2 - (pos_y * seq_h - clip_h / 2)) / clip_h * 100, 2)
    return pos_y, max(0.0, crop_top)


def build_apply_jsx(track_index: int, mapa: dict[int, tuple[float, float]]) -> str:
    """Position Y + Crop Top por índice de clipe, numa chamada."""
    dados = json.dumps({str(k): list(v) for k, v in mapa.items()})
    return f"""
      var mapa = {dados};
      var seq = app.project.activeSequence;
      if (!seq) return JSON.stringify({{success: false, error: "sem sequência ativa"}});
      var track = seq.videoTracks[{track_index}];
      var feito = 0, faltou = [];
      for (var i = 0; i < track.clips.numItems; i++) {{
        var alvo = mapa[String(i)];
        if (!alvo) continue;
        var c = track.clips[i], okPos = false, okCrop = false;
        for (var k = 0; k < c.components.numItems; k++) {{
          var comp = c.components[k], nome = String(comp.displayName);
          for (var j = 0; j < comp.properties.numItems; j++) {{
            var p = comp.properties[j], pn = String(p.displayName);
            try {{
              if (nome === "Motion" && pn === "Position") {{
                var atual = p.getValue();
                p.setValue([atual[0], alvo[0]], true); okPos = true;
              }}
              if (nome === "Crop" && pn === "Top") {{ p.setValue(alvo[1], true); okCrop = true; }}
            }} catch (e) {{}}
          }}
        }}
        if (okPos && okCrop) feito++; else faltou.push(i);
      }}
      return JSON.stringify({{success: true, feito: feito, faltou: faltou}});
    """


def read_camera(client: MCPStdioClient, seq_name: str, track_index: int,
                media_name: str) -> tuple[str, list[dict], int]:
    seqs = client.call_tool("list_sequences", {})
    seq_id = next((s["id"] for s in seqs.get("sequences", [])
                   if s.get("name") == seq_name), None)
    if not seq_id:
        raise MCPError(f"sequência {seq_name!r} não encontrada")
    client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})
    st = client.call_tool("get_sequence_structure", {"sequenceId": str(seq_id)})
    tracks = find_key(st, "videoTracks") or []
    seq_h = find_key(st, "height") or 1920
    track = next((t for t in tracks if t.get("index") == track_index), None)
    if not track:
        raise MCPError(f"track de vídeo {track_index} não existe")
    clips = [c for c in sorted(track.get("clips") or [],
                               key=lambda c: c.get("start", 0))
             if media_name in c.get("name", "")]
    if not clips:
        raise MCPError(f"nenhum clipe de câmera com {media_name!r} em V{track_index + 1}")
    return str(seq_id), clips, int(seq_h)


def fit(video: Path, seq_name: str, margin: int = DEFAULT_MARGIN,
        track_index: int = 1, media_name: str = "", timeout: float = 120.0,
        client: MCPStdioClient | None = None) -> dict:
    proprio = client is None
    if proprio:
        client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                                env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                                timeout=timeout)
        client.start()
    try:
        seq_id, clips, seq_h = read_camera(client, seq_name, track_index, media_name)
        probe = subprocess.run(
            ["/opt/homebrew/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True).stdout.strip()
        src_w, src_h = (int(v) for v in probe.split(",")[:2])
        props = client.call_tool("get_clip_properties", {"clipId": clips[0]["nodeId"]})
        scale = float(find_key(props, "scale") or 100)

        tmp = Path(tempfile.mkdtemp())
        mapa, medidos, sem_cabeca = {}, [], []
        for idx, c in enumerate(clips):
            ini, fim = c.get("inPoint", 0), c.get("outPoint", 0)
            ys = [y for y in (head_top(video, ini + (fim - ini) * f, tmp)
                              for f in SAMPLES) if y is not None]
            if not ys:
                sem_cabeca.append(idx)
                continue
            pos_y, crop = solve(min(ys), src_h, scale, seq_h, margin)
            mapa[idx] = (pos_y, crop)
            medidos.append(pos_y)

        if not mapa:
            raise MCPError("cabeça não detectada em nenhum clipe — "
                           "conferir se a fonte é a câmera do apresentador")
        r = client.call_tool("execute_extendscript",
                             {"script": build_apply_jsx(track_index, mapa)})
        if r.get("feito") != len(mapa):
            raise MCPError(f"aplicado em {r.get('feito')} de {len(mapa)} clipes "
                           f"(faltou: {r.get('faltou')})")
        client.call_tool("save_project", {})
        print(f"enquadramento por clipe: {len(mapa)} clipes, "
              f"Position Y de {min(medidos)} a {max(medidos)}, cabeça a ~{margin}px da divisa")
        if sem_cabeca:
            print(f"  AVISO: cabeça não detectada em {len(sem_cabeca)} clipes "
                  f"(índices {sem_cabeca}) — mantiveram o valor global")
        return {"clips": len(mapa), "sem_cabeca": sem_cabeca}
    finally:
        if proprio:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="fonte da câmera (o _12x)")
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--margin", type=int, default=DEFAULT_MARGIN)
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--media-name", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if not args.video.exists():
        sys.exit(f"não encontrado: {args.video}")
    media = args.media_name or args.video.stem[:12]
    fit(args.video, args.sequence_name, args.margin, args.camera_track,
        media, args.timeout)


if __name__ == "__main__":
    main()
