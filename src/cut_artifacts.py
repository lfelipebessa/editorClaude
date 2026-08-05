"""Persistência do CHECKPOINT 1: o corte aprovado vira artefato em disco.

Depois que o usuário fecha o corte (na timeline, ou direto da cutlist no fluxo
sem edição manual), grava-se:
- cutlist_final_<slug>.json  — segmentos do corte em tempo de FONTE
  (re-renderizável por render_ffmpeg SEM Premiere aberto)
- transcript_cut_<slug>.json — fala remapeada pro tempo do CORTE, com score,
  silences, ponteiro de volta pra fonte por palavra e tabela de offsets

Timestamps de fonte são relativos ao arquivo transcrito (na prática o `_12x` —
o campo source.speed_rate registra o fator; ver infer_speed_rate).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose import _word_in_range


def infer_speed_rate(transcript: dict, rate_if_12x: float) -> float:
    """O fator só se aplica se a fonte transcrita foi o arquivo acelerado."""
    stem = Path(transcript.get("source", {}).get("path", "")).stem
    return rate_if_12x if stem.endswith("_12x") else 1.0


def segments_from_cutlist(cutlist: dict) -> list[dict]:
    """cutlist automática -> segmentos {src_start, src_end} na ordem do corte."""
    return [{"src_start": s["start"], "src_end": s["end"]}
            for s in cutlist["segments"]]


def segments_from_clips(clips: list[dict]) -> list[dict]:
    """Clipes lidos da timeline -> segmentos em tempo de fonte, na ordem da
    timeline (inPoint/outPoint = trecho da fonte; start = posição na timeline)."""
    ordered = sorted(clips, key=lambda c: c["start"])
    return [{"src_start": c["inPoint"], "src_end": c["outPoint"]}
            for c in ordered]


def offset_table(segments: list[dict]) -> list[dict]:
    """Tabela explícita corte<->fonte (corte contíguo, offsets cumulativos)."""
    table, offset = [], 0.0
    for seg in segments:
        dur = seg["src_end"] - seg["src_start"]
        table.append({"cut_start": round(offset, 3),
                      "cut_end": round(offset + dur, 3),
                      "src_start": seg["src_start"],
                      "src_end": seg["src_end"]})
        offset += dur
    return table


def cut_to_src(t: float, table: list[dict]) -> float:
    """Tempo do corte -> tempo da fonte (devolver correções ao transcript)."""
    for row in table:
        if row["cut_start"] <= t <= row["cut_end"]:
            return round(row["src_start"] + (t - row["cut_start"]), 3)
    fim = table[-1]["cut_end"] if table else 0.0
    raise ValueError(f"t={t} fora do corte (0..{fim})")


def remap_words_rich(words: list[dict], table: list[dict]) -> list[dict]:
    """Como compose.remap_words, mas preservando score (e demais chaves) e
    guardando o ponteiro de volta pra fonte (src_start/src_end)."""
    out = []
    for i, row in enumerate(table):
        for w in words:
            if _word_in_range(w, row["src_start"], row["src_end"]):
                start = row["cut_start"] + max(w["start"], row["src_start"]) - row["src_start"]
                end = row["cut_start"] + min(w["end"], row["src_end"]) - row["src_start"]
                out.append({**w, "clip": i,
                            "start": round(start, 3), "end": round(end, 3),
                            "src_start": w["start"], "src_end": w["end"]})
    return out


def remap_silences(silences: list[dict], table: list[dict]) -> list[dict]:
    """Silêncios da fonte -> tempo do corte (só a parte que sobreviveu)."""
    out = []
    for row in table:
        for s in silences:
            lo = max(s["start"], row["src_start"])
            hi = min(s["end"], row["src_end"])
            if hi > lo:
                out.append(
                    {"start": round(row["cut_start"] + lo - row["src_start"], 3),
                     "end": round(row["cut_start"] + hi - row["src_start"], 3)})
    return sorted(out, key=lambda s: s["start"])


def write_cut_artifacts(transcript: dict, segments: list[dict], origem: str,
                        slug: str, speed_rate: float,
                        out_dir: Path = Path("output")) -> tuple[Path, Path]:
    """Grava cutlist_final_<slug>.json + transcript_cut_<slug>.json.

    origem: "timeline" (corte pós-edição humana) ou "cutlist" (automático) —
    os dois divergem depois do checkpoint; o campo diz qual verdade é esta.
    """
    table = offset_table(segments)
    # score default 0.0 espelha a convenção de transcribe.py (w.get("score", 0.0)) —
    # cobre palavras de transcripts antigos gravados antes desse default existir.
    words = [{**w, "score": w.get("score", 0.0)}
             for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]
    source = {**transcript["source"], "speed_rate": speed_rate}
    cut_duration = table[-1]["cut_end"] if table else 0.0

    cutlist_final = {"version": 1, "origem": origem, "source": source,
                     "segments": [{"start": s["src_start"], "end": s["src_end"]}
                                  for s in segments]}
    p_cut = out_dir / f"cutlist_final_{slug}.json"
    p_cut.write_text(json.dumps(cutlist_final, ensure_ascii=False, indent=2))

    transcript_cut = {"version": 1, "origem": origem, "source": source,
                      "cut_duration": cut_duration,
                      "offsets": table,
                      "silences": remap_silences(transcript.get("silences", []),
                                                 table),
                      "words": remap_words_rich(words, table)}
    p_tr = out_dir / f"transcript_cut_{slug}.json"
    p_tr.write_text(json.dumps(transcript_cut, ensure_ascii=False, indent=2))
    return p_cut, p_tr
