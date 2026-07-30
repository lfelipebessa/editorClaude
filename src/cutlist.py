"""Gera cut-list JSON a partir de um transcript word-level do WhisperX.

Remove: silêncios longos, gaguejos (palavras/n-gramas repetidos), falsos começos,
frases repetidas (retakes) e fillers isolados. O formato de saída é o contrato
documentado no README.

Uso:
    python src/cutlist.py output/transcript.json -o output/cutlist.json
"""

import argparse
import difflib
import json
import re
import string
from pathlib import Path

MAX_SILENCE = 0.8       # pausa acima disso vira corte
PAUSE_SPLIT = 0.6       # pausa que separa "frases" para análise
PAD_BEFORE = 0.15       # respiro mantido antes da fala
PAD_AFTER = 0.20        # respiro mantido depois da fala
FALSE_START_MAX_WORDS = 4
REPETITION_SIMILARITY = 0.8
FILLERS = {"uh", "um", "hum", "hmm", "eh", "ehh", "ã", "ãh", "hã", "éé", "ééé"}

_PUNCT = str.maketrans("", "", string.punctuation + "…—“”‘’")


def normalize(word: str) -> str:
    return word.translate(_PUNCT).casefold().strip()


def flatten_words(transcript: dict) -> list[dict]:
    words = []
    for seg in transcript["segments"]:
        for w in seg["words"]:
            words.append({**w, "norm": normalize(w["word"]), "keep": True, "reason": None})
    words.sort(key=lambda w: w["start"])
    return words


def drop(words: list[dict], indices: range | list[int], reason: str) -> None:
    for i in indices:
        if words[i]["keep"]:
            words[i]["keep"] = False
            words[i]["reason"] = reason


def remove_stutters(words: list[dict]) -> None:
    """Remove n-gramas imediatamente repetidos ("eu vou eu vou fazer"), mantendo a última ocorrência."""
    changed = True
    while changed:
        changed = False
        kept = [i for i, w in enumerate(words) if w["keep"]]
        for n in (3, 2, 1):
            for k in range(len(kept) - 2 * n + 1):
                a = [words[kept[k + j]]["norm"] for j in range(n)]
                b = [words[kept[k + n + j]]["norm"] for j in range(n)]
                if a == b and all(a):
                    gap = words[kept[k + n]]["start"] - words[kept[k + n - 1]]["end"]
                    if gap <= MAX_SILENCE:
                        drop(words, [kept[k + j] for j in range(n)], "stutter")
                        changed = True
                        break
            if changed:
                break


def remove_fillers(words: list[dict]) -> None:
    kept = [i for i, w in enumerate(words) if w["keep"]]
    for pos, i in enumerate(kept):
        if words[i]["norm"] not in FILLERS:
            continue
        gap_before = (words[i]["start"] - words[kept[pos - 1]]["end"]) if pos > 0 else 1.0
        gap_after = (words[kept[pos + 1]]["start"] - words[i]["end"]) if pos < len(kept) - 1 else 1.0
        if gap_before >= 0.15 or gap_after >= 0.15:
            drop(words, [i], "filler")


def group_phrases(words: list[dict]) -> list[list[int]]:
    """Agrupa índices de palavras mantidas em frases separadas por pausa > PAUSE_SPLIT."""
    kept = [i for i, w in enumerate(words) if w["keep"]]
    phrases, current = [], []
    for i in kept:
        if current and words[i]["start"] - words[current[-1]]["end"] > PAUSE_SPLIT:
            phrases.append(current)
            current = []
        current.append(i)
    if current:
        phrases.append(current)
    return phrases


def remove_false_starts(words: list[dict]) -> None:
    """Frase curta cujo início coincide com o começo da frase seguinte = falso começo."""
    phrases = group_phrases(words)
    for a, b in zip(phrases, phrases[1:]):
        if len(a) > FALSE_START_MAX_WORDS or len(a) > len(b):
            continue
        head_a = [words[i]["norm"] for i in a[:2]]
        head_b = [words[i]["norm"] for i in b[:2]]
        prefix = [words[i]["norm"] for i in b[:len(a)]]
        full_a = [words[i]["norm"] for i in a]
        if head_a == head_b or full_a == prefix:
            drop(words, a, "false_start")


def remove_repetitions(words: list[dict]) -> None:
    """Frases consecutivas quase idênticas (retakes): mantém a última tomada."""
    changed = True
    while changed:
        changed = False
        phrases = group_phrases(words)
        for a, b in zip(phrases, phrases[1:]):
            if len(a) < 3:
                continue
            text_a = " ".join(words[i]["norm"] for i in a)
            text_b = " ".join(words[i]["norm"] for i in b)
            ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
            if ratio >= REPETITION_SIMILARITY:
                drop(words, a, "repetition")
                changed = True
                break


def build_intervals(words: list[dict], duration: float) -> tuple[list[dict], list[dict]]:
    """Constrói segmentos mantidos (com padding) e lista de removidos.

    Um segmento quebra em pausa > MAX_SILENCE ou quando há palavra descartada
    no meio — senão o merge incluiria o trecho descartado no tempo do vídeo.
    """
    segments = []
    pending_drop = False
    for w in words:
        if not w["keep"]:
            pending_drop = True
            continue
        if segments and not pending_drop and w["start"] - segments[-1]["end"] <= MAX_SILENCE:
            segments[-1]["end"] = w["end"]
            segments[-1]["words"].append(w["word"])
        else:
            segments.append({"start": w["start"], "end": w["end"], "words": [w["word"]]})
        pending_drop = False

    # padding não pode reincluir palavras descartadas: clampa nos spans delas
    drop_spans = [(w["start"], w["end"]) for w in words if not w["keep"]]
    out = []
    for seg in segments:
        start = max(0.0, seg["start"] - PAD_BEFORE)
        end = min(duration, seg["end"] + PAD_AFTER)
        for ds, de in drop_spans:
            if de <= seg["start"]:
                start = max(start, de)
            if ds >= seg["end"]:
                end = min(end, ds)
        if out and start < out[-1]["end"]:
            start = out[-1]["end"]
        if end - start < 0.1:
            continue
        out.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": " ".join(seg["words"]),
            "reason": "speech",
        })

    removed = []
    dropped = [w for w in words if not w["keep"]]
    for w in dropped:
        removed.append({
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
            "reason": w["reason"],
            "text": w["word"],
        })
    cursor = 0.0
    for seg in out:
        if seg["start"] - cursor > MAX_SILENCE:
            removed.append({
                "start": round(cursor, 3),
                "end": round(seg["start"], 3),
                "reason": "silence",
                "text": "",
            })
        cursor = seg["end"]
    if duration - cursor > MAX_SILENCE:
        removed.append({"start": round(cursor, 3), "end": round(duration, 3),
                        "reason": "silence", "text": ""})
    removed.sort(key=lambda r: r["start"])
    return out, removed


def generate_cutlist(transcript: dict) -> dict:
    duration = transcript["source"]["duration"]
    words = flatten_words(transcript)

    remove_stutters(words)
    remove_fillers(words)
    remove_false_starts(words)
    remove_repetitions(words)

    segments, removed = build_intervals(words, duration)
    kept_duration = sum(s["end"] - s["start"] for s in segments)
    return {
        "version": 1,
        "source": transcript["source"],
        "segments": segments,
        "removed": removed,
        "stats": {
            "kept_duration": round(kept_duration, 3),
            "removed_duration": round(duration - kept_duration, 3),
            "segment_count": len(segments),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("output/cutlist.json"))
    args = parser.parse_args()

    transcript = json.loads(args.transcript.read_text())
    cutlist = generate_cutlist(transcript)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cutlist, ensure_ascii=False, indent=2))
    stats = cutlist["stats"]
    print(f"cut-list salva em {args.output}: {stats['segment_count']} segmentos, "
          f"mantém {stats['kept_duration']}s, remove {stats['removed_duration']}s")


if __name__ == "__main__":
    main()
