"""Núcleo do handoff de motions (spec 2026-08-04-motion-checkpoint-design):
palavras do corte aprovado + copy do vault -> handoff.md que o MotionSkills
consome (formato "copy timestamped", com tempos reais do corte final).

Diferença deliberada do merge_corrected_text das legendas: lá o texto
corrigido é a verdade e palavra falada sem par SOME (opcode delete não
emite). Aqui o FALADO é a verdade — palavra sem correspondência na copy fica
como o ASR ouviu, marcada matched=False (vira relatório de divergência).
Palavra da copy que não foi falada nunca entra no handoff.
"""

import re
from difflib import SequenceMatcher

from compose import normalize_text

FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
# marcador TELA: forma nua, bullet (-), blockquote (>), label em negrito
# (**TELA:**) e case-insensitive (Tela:). O prefixo de lista/quote não inclui
# "*" — senão ele engole o "**" de "**TELA:**" antes da alternativa bater.
TELA_RE = re.compile(
    r"^\s*(?:[->]\s*)*(?:\*\*TELA:\*\*|TELA\s*:)\s*(.+?)\s*$",
    re.IGNORECASE)
# prefixo de tempo de bloco na copy: `0:00`, `[00:19]`, `0:00 → 0:07`...
TIME_PREFIX_RE = re.compile(
    r"^\[?\d{1,2}:\d{2}(?:[.,]\d+)?\]?"
    r"(?:\s*(?:→|->|—|-)\s*\[?\d{1,2}:\d{2}(?:[.,]\d+)?\]?)?\s*")
# formatação inline do Obsidian que não sobrevive na PROSA (TELA mantém como
# está — motion designer lê o texto original do marcador).
MD_EMPHASIS_RE = re.compile(r"\*{1,3}(\S.*?\S|\S)\*{1,3}")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
# abaixo disso a similaridade de grafia é coincidência, não a mesma palavra
# dita diferente — vira substituição só quando bate de verdade.
SUBST_MIN_RATIO = 0.6


def parse_copy(md: str) -> tuple[list[dict], list[dict]]:
    """Copy do vault -> (chunks de prosa para o merge, marcadores TELA).

    Ignora frontmatter YAML, headings e prefixos de timestamp. Formatação
    inline do Obsidian (**negrito**/*itálico*, [[wikilink]]) é removida da
    PROSA antes de virar palavra — quem casa com o falado é o texto puro.
    O marcador TELA mantém seu texto como está no vault (não é prosa, é
    instrução visual literal para o motion designer). Cada TELA guarda as
    últimas 5 palavras de prosa (já limpas) vistas antes dele — a âncora
    que anchor_telas usa para reancorar no tempo real do corte.
    """
    md = FRONTMATTER_RE.sub("", md)
    prose_words, telas = [], []
    for raw in md.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = TELA_RE.match(line)
        if m:
            telas.append({"text": m.group(1).strip(),
                          "anchor": prose_words[-5:]})
            continue
        line = TIME_PREFIX_RE.sub("", line)
        line = WIKILINK_RE.sub(r"\1", line)
        line = MD_EMPHASIS_RE.sub(r"\1", line)
        if line:
            prose_words.extend(line.split())
    chunks = [{"text": " ".join(prose_words)}] if prose_words else []
    return chunks, telas


def merge_with_copy(words: list[dict], copy_chunks: list[dict]) -> list[dict]:
    """Palavras do corte (verdade de conteúdo e tempo) + copy (verdade de
    grafia) -> palavras com grafia corrigida e proveniência `matched`.

    equal: grafia da copy, timing do falado, matched=True.

    replace: o SequenceMatcher pareou um trecho falado com um trecho da
    copy, mas isso não garante que seja A MESMA palavra escrita diferente —
    pode ser um "eu" da copy caindo por acaso no lugar de "terminei a call"
    no alinhamento global. Por isso replace passa por um gate de
    similaridade de grafia (SUBST_MIN_RATIO) antes de virar substituição:
    - N:1 (vários tokens falados -> um token da copy, ex. ASR "chat" "gpt"
      para copy "ChatGPT"): só colapsa em uma palavra se a grafia batida
      for parecida o bastante; timing do span inteiro (start do primeiro,
      end do último). Se não bater, cai pro caso 1:1 abaixo.
    - 1:1 (index a index, até onde os dois lados alcançarem): substitui
      só o par cuja grafia é parecida (ratio >= SUBST_MIN_RATIO) — troca
      de palavra genuinamente diferente (baixa similaridade) fica como o
      ASR ouviu, matched=False, nunca vira a palavra errada da copy.
    - sobra de um lado (span mais longo que tokens): fica como ASR,
      matched=False.

    delete (falado sem par na copy): fica como o ASR ouviu, matched=False.
    insert (copy nunca falada): descartada — nunca entra no handoff.
    """
    if not copy_chunks:
        return [{**w, "matched": False} for w in words]
    corr_tokens = [t for c in copy_chunks for t in c["text"].split()]
    a = [normalize_text(w["word"]) for w in words]
    b = [normalize_text(t) for t in corr_tokens]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out.append({**words[i1 + k], "word": corr_tokens[j1 + k],
                            "matched": True})
        elif tag == "replace":
            span, tokens = words[i1:i2], corr_tokens[j1:j2]
            if (len(tokens) == 1 and len(span) > 1 and SequenceMatcher(
                    None, "".join(a[i1:i2]), b[j1]).ratio() >= SUBST_MIN_RATIO):
                out.append({**span[0], "end": span[-1]["end"],
                            "word": tokens[0], "matched": True})
                continue
            n = min(len(span), len(tokens))
            for k in range(n):
                if SequenceMatcher(None, a[i1 + k],
                                   b[j1 + k]).ratio() >= SUBST_MIN_RATIO:
                    out.append({**span[k], "word": tokens[k], "matched": True})
                else:
                    out.append({**span[k], "matched": False})
            for w in span[n:]:
                out.append({**w, "matched": False})
        elif tag == "delete":
            for w in words[i1:i2]:
                out.append({**w, "matched": False})
    return out
