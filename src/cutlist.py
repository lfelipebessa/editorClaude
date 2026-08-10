"""Gera cut-list JSON a partir de um transcript word-level do WhisperX.

Remove: silêncios longos, gaguejos (palavras/n-gramas repetidos), falsos começos,
frases repetidas (retakes) e fillers isolados. O formato de saída é o contrato
documentado no README.

Uso:
    python src/cutlist.py output/transcript.json -o output/cutlist.json
    python src/cutlist.py output/transcript.json --preset seco   # jump cut agressivo
"""

import argparse
import difflib
import json
import string
import sys
from pathlib import Path

MAX_SILENCE = 0.8       # pausa acima disso vira corte
PAUSE_SPLIT = 0.6       # pausa que separa "frases" para análise
PAD_BEFORE = 0.15       # respiro mantido antes da fala
PAD_AFTER = 0.20        # respiro mantido depois da fala
MIN_SEGMENT = 0.2       # duração mínima de um segmento após trims
FALSE_START_MAX_WORDS = 4
REPETITION_SIMILARITY = 0.8
RETAKE_BREATH = 0.35     # respiro que separa duas tomadas
RETAKE_MIN_TOKENS = 4    # tomada menor que isso não é avaliada (evita falso positivo)
RETAKE_CONTAINMENT = 0.75  # fração dos tokens da tomada menor que reaparece na seguinte
RETAKE_WINDOW = 30.0     # janela em que duas tomadas contam como retake
RETAKE_LOOKAHEAD = 3     # tomadas à frente comparadas (fragmento curto no meio)
FILLERS = {"uh", "um", "hum", "hmm", "eh", "ehh", "ã", "ãh", "hã", "éé", "ééé"}

DEFAULTS = {
    "max_word_gap": MAX_SILENCE,  # gap entre palavras que vira corte
    "pad_before": PAD_BEFORE,
    "pad_after": PAD_AFTER,
    "trim_start": 0.0,            # corta DENTRO da fala no início do segmento
    "trim_end": 0.0,              # corta DENTRO da fala no fim do segmento
    "trim_min_duration": 0.8,     # segmento abaixo disso não recebe trim algum
    "trim_max_fraction": 0.12,    # trim por borda limitado a esta fração da duração
    "trim_max_word_fraction": 0.3,  # trim limitado a esta fração da palavra da borda
    "min_word_protect": 0.4,      # palavra da borda abaixo disso: trim zero naquela borda
    "short_word_end_margin": 0.5,  # teto da extensão até o silêncio real após palavra final curta
    "min_segment": MIN_SEGMENT,
}

# presets vivem em styles/<nome>.json — fonte única de verdade, versionada
STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


def load_style(name: str) -> dict:
    path = STYLES_DIR / f"{name}.json"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in STYLES_DIR.glob("*.json"))) or "nenhum"
        sys.exit(f"style '{name}' não encontrado em {STYLES_DIR} (disponíveis: {available})")
    style = json.loads(path.read_text())
    if "cut" not in style:
        sys.exit(f"style '{name}' sem a seção 'cut': {path}")
    return style

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


def split_takes(words: list[dict], gap: float = RETAKE_BREATH) -> list[list[int]]:
    """Divide as palavras mantidas em tomadas, separadas por respiro >= gap."""
    kept = [i for i, w in enumerate(words) if w["keep"]]
    takes, cur = [], []
    for i in kept:
        if cur and words[i]["start"] - words[cur[-1]]["end"] >= gap:
            takes.append(cur)
            cur = []
        cur.append(i)
    if cur:
        takes.append(cur)
    return takes


def remove_retakes(words: list[dict], window: float = RETAKE_WINDOW) -> None:
    """Tomada refeita (retake reformulado): mantém a última tentativa.

    O detector por similaridade de CARACTERES entre frases só pega repetição
    quase literal. Na prática a tomada é reformulada ("ela permite que você
    construa" -> "...reconstrua uma imagem ou um objeto 3D" -> "...um objeto ou
    uma imagem que você tenha como um modelo 3D"): nenhuma passa de 0.70 de
    ratio, e comparar a ABERTURA exata também falha porque o transcript perde
    palavras (o take vem sem o "Que" inicial).

    O que se sustenta é CONTAINMENT de tokens entre tomadas consecutivas: se
    quase todo token da tomada menor reaparece na seguinte, a primeira era
    ensaio. Consecutivas + janela de tempo evitam casar fala legítima distante
    que por acaso repita palavras.
    """
    changed = True
    while changed:
        changed = False
        takes = split_takes(words)
        # olhar até RETAKE_LOOKAHEAD tomadas à frente: entre duas tentativas
        # costuma sobrar um fragmento curto ("há", "a") que, sozinho, não passa
        # de RETAKE_MIN_TOKENS e escondia o par da comparação
        pares = [(takes[i], takes[j])
                 for i in range(len(takes))
                 for j in range(i + 1, min(i + 1 + RETAKE_LOOKAHEAD, len(takes)))]
        for a, b in pares:
            ta = {words[i]["norm"] for i in a if words[i]["norm"]}
            tb = {words[i]["norm"] for i in b if words[i]["norm"]}
            if min(len(ta), len(tb)) < RETAKE_MIN_TOKENS:
                continue
            if words[b[0]]["start"] - words[a[0]]["start"] > window:
                continue
            menor, maior = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if len(menor & maior) / len(menor) < RETAKE_CONTAINMENT:
                continue
            # a tomada pode trazer fala BOA emendada antes do ensaio ("focado em
            # acabar com o AI slop. Que são aqueles designs genéricos?"): remove
            # só de onde o trecho repetido começa, nunca a tomada inteira
            seq_a = [words[i]["norm"] for i in a]
            seq_b = [words[i]["norm"] for i in b]
            bloco = max(difflib.SequenceMatcher(None, seq_a, seq_b, autojunk=False)
                        .get_matching_blocks(), key=lambda m: m.size)
            corte = bloco.a if bloco.size >= RETAKE_MIN_TOKENS else 0
            if len(a) - corte < RETAKE_MIN_TOKENS:
                continue
            drop(words, a[corte:], "retake")
            changed = True
            break


def subtract_silences(segments: list[dict], silences: list[dict],
                      kept_words: list[dict], cfg: dict) -> list[dict]:
    """Corta silêncios detectados no áudio de dentro dos segmentos mantidos.

    Necessário porque o aligner às vezes estica uma palavra por cima da pausa,
    fazendo o silêncio 'desaparecer' dos timestamps do transcript. O texto de
    cada pedaço é recomputado a partir das palavras que começam dentro dele;
    pedaços sem palavra alguma (respiração, ruído entre silêncios) são descartados.
    """
    for sil in silences:
        cut_start = sil["start"] + cfg["pad_after"]
        cut_end = sil["end"] - cfg["pad_before"]
        if cut_end - cut_start < cfg["max_word_gap"]:
            continue
        result = []
        for seg in segments:
            if cut_end <= seg["start"] or cut_start >= seg["end"]:
                result.append(seg)
                continue
            left = {**seg, "end": round(max(seg["start"], cut_start), 3)}
            right = {**seg, "start": round(min(seg["end"], cut_end), 3)}
            if left["end"] - left["start"] >= 0.1:
                result.append(left)
            if right["end"] - right["start"] >= 0.1:
                result.append(right)
        segments = result

    # o aligner estica só o fim das palavras; o início é confiável, então cada
    # palavra pertence ao pedaço em que começa
    out = []
    for seg in segments:
        texts = [w["word"] for w in kept_words
                 if seg["start"] <= w["start"] < seg["end"]]
        if texts:
            out.append({**seg, "text": " ".join(texts)})
    return out


def apply_edge_trims(segments: list[dict], cfg: dict, kept_words: list[dict],
                     silences: list[dict]) -> list[dict]:
    """Trim negativo adaptativo, consciente de segmento E de palavra.

    Trim fixo come palavras curtas inteiras, então a regra escala em dois níveis:
    - segmento abaixo de trim_min_duration: nenhum trim;
    - cada borda perde no máximo trim_max_fraction da duração do segmento
      E trim_max_word_fraction da duração da palavra daquela borda;
    - palavra da borda mais curta que min_word_protect: trim zero naquela borda;
    - segmentos longos com palavras longas nas bordas: trim_start/trim_end na íntegra.
    Se o resultado ficaria menor que min_segment, mantém as bordas originais.

    Sigla/palavra curta no FIM ("CRM"): o aligner costuma fechar a palavra antes
    da fala acabar. Se a última palavra é curta e há silêncio detectado logo à
    frente, o fim do segmento estende até o início do silêncio real (teto:
    short_word_end_margin), nunca invadindo o segmento seguinte.
    """
    trim_start, trim_end = cfg["trim_start"], cfg["trim_end"]
    if trim_start <= 0 and trim_end <= 0:
        return segments
    out = []
    for i, seg in enumerate(segments):
        inside = [w for w in kept_words if seg["start"] <= w["start"] < seg["end"]]
        if not inside:
            out.append(seg)
            continue
        duration = seg["end"] - seg["start"]
        first, last = inside[0], inside[-1]
        first_dur = first["end"] - first["start"]
        last_dur = last["end"] - last["start"]
        start, end = seg["start"], seg["end"]

        if duration >= cfg["trim_min_duration"]:
            allowed = cfg["trim_max_fraction"] * duration
            ts = 0.0 if first_dur < cfg["min_word_protect"] else min(
                trim_start, allowed, cfg["trim_max_word_fraction"] * first_dur)
            te = 0.0 if last_dur < cfg["min_word_protect"] else min(
                trim_end, allowed, cfg["trim_max_word_fraction"] * last_dur)
            if (seg["end"] - te) - (seg["start"] + ts) >= cfg["min_segment"]:
                start, end = seg["start"] + ts, seg["end"] - te

        if last_dur < cfg["min_word_protect"] and cfg["short_word_end_margin"] > 0:
            next_sil = min((s["start"] for s in silences if s["start"] >= end - 0.01),
                           default=None)
            if next_sil is not None:
                limit = seg["end"] + cfg["short_word_end_margin"]
                if i + 1 < len(segments):
                    limit = min(limit, segments[i + 1]["start"])
                end = max(end, min(next_sil, limit))

        out.append({**seg, "start": round(start, 3), "end": round(end, 3)})
    return out


def build_intervals(words: list[dict], duration: float, silences: list[dict],
                    cfg: dict) -> tuple[list[dict], list[dict]]:
    """Constrói segmentos mantidos (com padding/trim) e lista de removidos.

    Um segmento quebra em pausa > max_word_gap ou quando há palavra descartada
    no meio — senão o merge incluiria o trecho descartado no tempo do vídeo.
    """
    segments = []
    pending_drop = False
    for w in words:
        if not w["keep"]:
            pending_drop = True
            continue
        if segments and not pending_drop and w["start"] - segments[-1]["end"] <= cfg["max_word_gap"]:
            segments[-1]["end"] = w["end"]
            segments[-1]["words"].append(w["word"])
        else:
            segments.append({"start": w["start"], "end": w["end"], "words": [w["word"]]})
        pending_drop = False

    # padding não pode reincluir palavras descartadas: clampa nos spans delas
    drop_spans = [(w["start"], w["end"]) for w in words if not w["keep"]]
    out = []
    for seg in segments:
        start = max(0.0, seg["start"] - cfg["pad_before"])
        end = min(duration, seg["end"] + cfg["pad_after"])
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

    kept_words = [w for w in words if w["keep"]]
    out = subtract_silences(out, silences, kept_words, cfg)
    out = apply_edge_trims(out, cfg, kept_words, silences)

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
        if seg["start"] - cursor > cfg["max_word_gap"]:
            removed.append({
                "start": round(cursor, 3),
                "end": round(seg["start"], 3),
                "reason": "silence",
                "text": "",
            })
        cursor = seg["end"]
    if duration - cursor > cfg["max_word_gap"]:
        removed.append({"start": round(cursor, 3), "end": round(duration, 3),
                        "reason": "silence", "text": ""})
    removed.sort(key=lambda r: r["start"])
    return out, removed


def generate_cutlist(transcript: dict, settings: dict | None = None) -> dict:
    cfg = {**DEFAULTS, **(settings or {})}
    duration = transcript["source"]["duration"]
    words = flatten_words(transcript)

    remove_stutters(words)
    remove_fillers(words)
    remove_false_starts(words)
    remove_repetitions(words)
    remove_retakes(words)

    segments, removed = build_intervals(words, duration, transcript.get("silences", []), cfg)
    kept_duration = sum(s["end"] - s["start"] for s in segments)
    return {
        "version": 1,
        "source": transcript["source"],
        "settings": cfg,
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
    parser.add_argument("--preset",
                        help="nome de um style em styles/ (ex.: seco = jump cut agressivo)")
    parser.add_argument("--trim-start", type=float, default=None,
                        help="segundos cortados DENTRO da fala no início de cada segmento")
    parser.add_argument("--trim-end", type=float, default=None,
                        help="segundos cortados DENTRO da fala no fim de cada segmento")
    parser.add_argument("--max-word-gap", type=float, default=None,
                        help="gap entre palavras (s) acima do qual vira corte")
    args = parser.parse_args()

    settings = dict(load_style(args.preset)["cut"]) if args.preset else {}
    for key in ("trim_start", "trim_end", "max_word_gap"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value

    transcript = json.loads(args.transcript.read_text())
    cutlist = generate_cutlist(transcript, settings)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cutlist, ensure_ascii=False, indent=2))
    stats = cutlist["stats"]
    print(f"cut-list salva em {args.output}: {stats['segment_count']} segmentos, "
          f"mantém {stats['kept_duration']}s, remove {stats['removed_duration']}s")


if __name__ == "__main__":
    main()
