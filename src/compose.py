"""Núcleo do composer vertical (Fase 3): remap de palavras pelo corte,
legendas editáveis (SRT) e resolvedor de âncoras textuais do motion-manifest.

Contrato (ver note 01-spec-vertical-composer no Maestri):
- palavras do WhisperX (tempo do bruto) -> remap_words -> tempo do corte final
- motion-manifest: cada cena tem `match` (primeiras palavras do bloco de fala);
  find_scene_starts casa as âncoras com fuzzy matching sequencial -> offsets
  absolutos no corte. Re-cortou? Roda de novo e os offsets se atualizam.
- Legendas NUNCA são só pixel: o SRT é a fonte de verdade editável (o usuário
  corrige palavra errada no arquivo ou na caption track do Premiere); o burn
  do ffmpeg é derivado dele.
"""

import re
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    """minúsculas, sem pontuação, espaços colapsados — para casar âncoras."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def remap_words(words: list[dict], cut_segments: list[dict]) -> list[dict]:
    """Palavras com tempo do bruto -> tempo do corte final.

    Palavra pertence ao segmento que contém seu ponto médio; palavras em
    região removida são descartadas (não existem no vídeo final).
    """
    out, offset = [], 0.0
    for seg in cut_segments:
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            if seg["start"] <= mid < seg["end"]:
                start = offset + max(w["start"], seg["start"]) - seg["start"]
                end = offset + min(w["end"], seg["end"]) - seg["start"]
                out.append({"word": w["word"],
                            "start": round(start, 3), "end": round(end, 3)})
        offset += seg["end"] - seg["start"]
    return out


def remap_words_by_clips(words: list[dict], clips: list[dict]) -> list[dict]:
    """Remap pelo layout ATUAL da timeline (pós-edição manual do usuário).

    Cada clip = {start (posição na timeline), inPoint, outPoint (trecho do
    bruto)}. Diferente do remap_words (cutlist cumulativa), aqui a posição
    vem do próprio clipe — sobrevive a cortes, encurtamentos e gaps.
    """
    out = []
    for clip in sorted(clips, key=lambda c: c["start"]):
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            if clip["inPoint"] <= mid < clip["outPoint"]:
                start = clip["start"] + max(w["start"], clip["inPoint"]) - clip["inPoint"]
                end = clip["start"] + min(w["end"], clip["outPoint"]) - clip["inPoint"]
                out.append({"word": w["word"],
                            "start": round(start, 3), "end": round(end, 3)})
    return out


def merge_corrected_text(words: list[dict],
                         corrected_chunks: list[dict]) -> list[dict]:
    """Texto do SRT corrigido (INSTALEI, CLAUDE, ADMIN...) + timing do
    transcript -> palavras corrigidas com timing. Alinha os dois fluxos de
    tokens com SequenceMatcher; substituição herda o timing das originais;
    palavra removida na correção some; inserção cola na anterior.
    """
    corr_tokens = [t for c in corrected_chunks for t in c["text"].split()]
    a = [normalize_text(w["word"]) for w in words]
    b = [normalize_text(t) for t in corr_tokens]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = words[i1 + k]
                out.append({"word": corr_tokens[j1 + k],
                            "start": w["start"], "end": w["end"]})
        elif tag == "replace":
            span, tokens = words[i1:i2], corr_tokens[j1:j2]
            t0, t1 = span[0]["start"], span[-1]["end"]
            n = len(tokens)
            for k, token in enumerate(tokens):
                out.append({"word": token,
                            "start": round(t0 + (t1 - t0) * k / n, 3),
                            "end": round(t0 + (t1 - t0) * (k + 1) / n, 3)})
        elif tag == "insert":
            anchor = out[-1]["end"] if out else 0.0
            for token in corr_tokens[j1:j2]:
                out.append({"word": token, "start": anchor, "end": anchor})
    return out


def group_captions(words: list[dict], max_words: int = 3,
                   max_gap: float = 0.6, max_dur: float = 2.5) -> list[dict]:
    """Agrupa palavras em legendas curtas estilo social."""
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words
                    or w["start"] - cur[-1]["end"] > max_gap
                    or w["end"] - cur[0]["start"] > max_dur):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return [{"text": " ".join(w["word"] for w in g),
             "start": g[0]["start"], "end": g[-1]["end"]} for g in groups]


def find_scene_starts(scenes: list[dict], words: list[dict]) -> list[float]:
    """Resolve a âncora textual de cada cena para tempo do corte final.

    Fuzzy (SequenceMatcher) com restrição sequencial: cada cena só pode
    começar depois da anterior. A cena 1 é sempre 0.0 — motion cobre o
    vídeo desde o primeiro frame.
    """
    tokens = [normalize_text(w["word"]) for w in words]
    starts, pos = [], 0
    for i, scene in enumerate(scenes):
        target = normalize_text(scene["match"]).split()
        n = len(target)
        best_score, best_j = -1.0, pos
        for j in range(pos, max(pos + 1, len(tokens) - n + 1)):
            window = " ".join(tokens[j:j + n])
            score = SequenceMatcher(None, " ".join(target), window).ratio()
            if score > best_score:
                best_score, best_j = score, j
        starts.append(0.0 if i == 0 else round(words[best_j]["start"], 3))
        pos = best_j + 1
    return starts


def parse_brief_scenes(md: str) -> list[dict]:
    """Extrai as cenas da tabela do brief.md do MotionSkills.

    Linhas `| NN | "Trecho..." | ... | Dur | Loop | Layout |` viram
    {num, match (primeiras 8 palavras do trecho), loop}. A âncora textual
    vem direto do trecho de fala que o próprio brief associa à cena.
    """
    scenes = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7 or not re.fullmatch(r"\d{2}", cells[0]):
            continue
        # âncora curta (5 palavras): prende no COMEÇO da seção; trecho longo
        # arrasta o match para o meio quando a fala real diverge do brief
        trecho = cells[1].strip().strip('"').lstrip("…").strip()
        scenes.append({"num": cells[0],
                       "match": " ".join(trecho.split()[:5]),
                       "loop": cells[5].strip().lower().startswith("s")})
    return scenes


def parse_srt(text: str) -> list[dict]:
    """SRT (a fonte de verdade editável) -> chunks {text, start, end}."""
    pattern = re.compile(
        r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")
    chunks = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        if len(lines) < 3:
            continue
        m = pattern.match(lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        chunks.append({
            "text": " ".join(lines[2:]),
            "start": round(g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, 3),
            "end": round(g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, 3)})
    return chunks


def format_srt(chunks: list[dict]) -> str:
    """Legendas agrupadas -> SRT (fonte de verdade editável)."""
    def ts(t: float) -> str:
        ms = round(t * 1000)
        h, rest = divmod(ms, 3600_000)
        m, rest = divmod(rest, 60_000)
        s, ms = divmod(rest, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = [f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n"
              for i, c in enumerate(chunks, 1)]
    return "\n".join(blocks) + "\n"
