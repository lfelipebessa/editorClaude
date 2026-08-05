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

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
TELA_RE = re.compile(r"^\s*TELA:\s*(.+)$")
# prefixo de tempo de bloco na copy: `0:00`, `[00:19]`, `0:00 → 0:07`...
TIME_PREFIX_RE = re.compile(
    r"^\[?\d{1,2}:\d{2}(?:[.,]\d+)?\]?"
    r"(?:\s*(?:→|->|—|-)\s*\[?\d{1,2}:\d{2}(?:[.,]\d+)?\]?)?\s*")


def parse_copy(md: str) -> tuple[list[dict], list[dict]]:
    """Copy do vault -> (chunks de prosa para o merge, marcadores TELA).

    Ignora frontmatter YAML, headings e prefixos de timestamp. Cada TELA
    guarda as últimas 5 palavras de prosa vistas antes dele — a âncora que
    anchor_telas usa para reancorar no tempo real do corte.
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
        if line:
            prose_words.extend(line.split())
    chunks = [{"text": " ".join(prose_words)}] if prose_words else []
    return chunks, telas


def merge_with_copy(words: list[dict], copy_chunks: list[dict]) -> list[dict]:
    """Palavras do corte (verdade de conteúdo e tempo) + copy (verdade de
    grafia) -> palavras com grafia corrigida e proveniência `matched`.

    equal/replace: grafia da copy, timing do falado. replace pareia 1:1 até
    onde dá (ASR ouviu "chat gpt" para "ChatGPT" — sobra fica como ASR).
    delete (falado sem par): fica como o ASR ouviu, matched=False.
    insert (copy nunca falada): descartada.
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
            n = min(len(span), len(tokens))
            for k in range(n):
                out.append({**span[k], "word": tokens[k], "matched": True})
            for w in span[n:]:
                out.append({**w, "matched": False})
        elif tag == "delete":
            for w in words[i1:i2]:
                out.append({**w, "matched": False})
    return out
