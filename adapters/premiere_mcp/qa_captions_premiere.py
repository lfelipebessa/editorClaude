"""QA de legenda: re-transcreve o áudio do CORTE FINAL da timeline e diffa
contra o SRT da legenda.

Pega o que a revisão manual não vê: frase que o WhisperX engoliu no bruto
(ex.: "Terminei a call" virou a palavra falsa "Eu" — e palavra que não existe
no transcript nunca vira legenda) e legenda órfã (texto sem fala). O diff tem
ruído esperado em borda de corte (palavra clipada confunde o ASR) — conferir
no olho antes de agir; dois ASRs discordando da MESMA região é o sinal forte.

Conserto de frase engolida: inserir as palavras no transcript_<slug>.json com
os timestamps de fonte que este QA imprime, adicionar os tokens no SRT
corrigido e rodar recaption_premiere.py de novo.

Uso (Premiere aberto, bridge ativa):
    python adapters/premiere_mcp/qa_captions_premiere.py <video_12x> <srt> \
        --sequence-name reel_<slug> [--media-name dji_]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recaption_premiere import read_voice_clips
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from compose import normalize_text, parse_srt

TRANSCRIBE = Path(__file__).resolve().parent.parent.parent / "src" / "transcribe.py"


def read_clips(sequence_name: str, media_name: str, timeout: float) -> list[dict]:
    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=timeout)
    client.start()
    try:
        seqs = client.call_tool("list_sequences", {})
        seq_id = next((s["id"] for s in seqs.get("sequences", [])
                       if s.get("name") == sequence_name), None)
        if not seq_id:
            raise MCPError(f"sequência {sequence_name!r} não encontrada")
        client.call_tool("set_active_sequence", {"sequenceId": seq_id})
        return sorted(read_voice_clips(client, media_name),
                      key=lambda c: c["start"])
    finally:
        client.close()


def concat_voice_audio(video: Path, clips: list[dict],
                       out_wav: Path) -> list[dict]:
    """Concatena os trechos de voz num wav; devolve o mapa de tempos."""
    filters, inputs, mapping = [], [], []
    cum = 0.0
    for i, c in enumerate(clips):
        dur = c["outPoint"] - c["inPoint"]
        filters.append(f"[0:a]atrim=start={c['inPoint']}:end={c['outPoint']},"
                       f"asetpts=PTS-STARTPTS[a{i}]")
        inputs.append(f"[a{i}]")
        mapping.append({"qa_start": cum, "qa_end": cum + dur,
                        "src_in": c["inPoint"], "timeline": c["start"]})
        cum += dur
    graph = (";".join(filters) + ";" + "".join(inputs)
             + f"concat=n={len(clips)}:v=0:a=1[out]")
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-filter_complex", graph,
                    "-map", "[out]", "-ac", "1", "-ar", "16000", str(out_wav)],
                   check=True, capture_output=True)
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="fonte da voz (o _12x)")
    parser.add_argument("srt", type=Path, help="SRT da legenda atual")
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--language", default="pt")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    for p in (args.video, args.srt):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")

    clips = read_clips(args.sequence_name, args.media_name, args.timeout)
    print(f"{len(clips)} clipes de voz lidos da timeline")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "qa.wav"
        mapping = concat_voice_audio(args.video, clips, wav)
        qa_json = Path(tmp) / "qa.json"
        subprocess.run([sys.executable, str(TRANSCRIBE), str(wav),
                        "-o", str(qa_json), "--language", args.language],
                       check=True, capture_output=True)
        qa = json.loads(qa_json.read_text())

    qa_words = [w for s in qa["segments"] for w in s.get("words", [])
                if "start" in w]
    caps = parse_srt(args.srt.read_text())
    srt_tokens = [t for c in caps for t in c["text"].split()]

    def locate(t: float) -> str:
        row = next((m for m in mapping if m["qa_start"] <= t < m["qa_end"]),
                   mapping[-1])
        tl = row["timeline"] + (t - row["qa_start"])
        src = row["src_in"] + (t - row["qa_start"])
        return f"timeline {tl:6.2f}s  fonte {src:7.2f}s"

    a = [normalize_text(w["word"]) for w in qa_words]
    b = [normalize_text(t) for t in srt_tokens]
    diffs = [op for op in SequenceMatcher(None, a, b, autojunk=False)
             .get_opcodes() if op[0] != "equal"]
    if not diffs:
        print("legenda bate 100% com o áudio do corte final.")
        return
    print(f"{len(diffs)} diferenças falado vs legenda "
          "(ruído de borda de corte é esperado):")
    for tag, i1, i2, j1, j2 in diffs:
        falado = " ".join(w["word"] for w in qa_words[i1:i2]) or "-"
        legenda = " ".join(srt_tokens[j1:j2]) or "-"
        pos = (locate(qa_words[min(i1, len(qa_words) - 1)]["start"])
               if qa_words else "?")
        print(f"  [{tag:^7}] {pos} | falado: {falado!r} | legenda: {legenda!r}")


if __name__ == "__main__":
    main()
