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

from core.transcript import normalize_text

FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
# marcador TELA: forma nua, bullet (-), blockquote (>), label em negrito
# (**TELA:**) e case-insensitive (Tela:). O prefixo de lista/quote não inclui
# "*" — senão ele engole o "**" de "**TELA:**" antes da alternativa bater.
TELA_RE = re.compile(
    r"^\s*(?:[->]\s*|\*\s+)*"
    r"(?:\*\*TELA:\*\*|\*TELA:\*|\*{1,2}TELA\*{1,2}\s*:|TELA\s*:)\s*(.+?)\s*$",
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


def build_blocks(bounds: list[tuple[float, float]],
                 min_dur: float = 1.5) -> list[dict]:
    """Clipes do corte (tempo do corte final) -> blocos do handoff.

    Bloco com menos de min_dur funde com o SEGUINTE (jump cuts do preset
    seco são curtos demais como unidade de cena — regra do spec); sobra
    final curta funde com o anterior.
    """
    blocks, cur_start, cur_end = [], None, None
    for start, end in bounds:
        if cur_start is None:
            cur_start, cur_end = start, end
        else:
            cur_end = end
        if cur_end - cur_start >= min_dur:
            blocks.append({"start": cur_start, "end": cur_end})
            cur_start = None
    if cur_start is not None:
        if blocks:
            blocks[-1]["end"] = cur_end
        else:
            blocks.append({"start": cur_start, "end": cur_end})
    return blocks


def assign_words(blocks: list[dict], words: list[dict]) -> None:
    """Palavra pertence ao bloco em que COMEÇA (mesma regra do composer)."""
    for b in blocks:
        b["words"] = [w for w in words if b["start"] <= w["start"] < b["end"]]


def anchor_telas(telas: list[dict], words: list[dict],
                 blocks: list[dict]) -> None:
    """Reancora cada TELA: no bloco onde o trecho de copy anterior a ela foi
    realmente falado (fuzzy sequencial, mesmo esquema do find_scene_starts).
    Sem âncora (TELA no começo da copy) -> bloco 1.
    """
    if not blocks:
        return
    tokens = [normalize_text(w["word"]) for w in words]
    pos = 0
    for tela in telas:
        target = [normalize_text(t) for t in tela["anchor"]
                  if normalize_text(t)]
        if not target or not words:
            blocks[0].setdefault("telas", []).append(tela["text"])
            continue
        n = len(target)
        best_score, best_j = -1.0, pos
        for j in range(pos, max(pos + 1, len(tokens) - n + 1)):
            window = " ".join(tokens[j:j + n])
            score = SequenceMatcher(None, " ".join(target), window).ratio()
            if score > best_score:
                best_score, best_j = score, j
        t = words[min(best_j + n - 1, len(words) - 1)]["end"]
        block = next((b for b in blocks if b["start"] <= t <= b["end"]),
                     blocks[-1])
        block.setdefault("telas", []).append(tela["text"])
        pos = best_j + 1


DIVERGENCE_THRESHOLD = 0.5  # fração de palavras sem par na copy


def divergent_blocks(blocks: list[dict]) -> list[int]:
    """Índices (1-based) dos blocos onde a maioria das palavras não casou
    com a copy — o relatório que vai junto no envio (não bloqueia)."""
    out = []
    for i, b in enumerate(blocks, 1):
        n = len(b.get("words", []))
        if n and sum(1 for w in b["words"]
                     if not w.get("matched")) / n > DIVERGENCE_THRESHOLD:
            out.append(i)
    return out


def _fmt_time(t: float) -> str:
    ds = round(t * 10)          # décimos: arredonda ANTES de fatiar
    m, ds = divmod(ds, 600)
    return f"{m}:{ds / 10:04.1f}"


def format_handoff(slug: str, blocks: list[dict],
                   copy_ref: str | None) -> str:
    """Blocos anotados -> handoff.md (contrato v1 do spec)."""
    total = blocks[-1]["end"] if blocks else 0.0
    lines = [f"# Handoff — {slug}  (v1)",
             f"Fonte: corte aprovado (EditorClaude) · Corte: {total:.1f}s · "
             f"Blocos: {len(blocks)}"]
    lines.append(f"Copy: [[{copy_ref}]]" if copy_ref else
                 "Copy: NENHUMA — texto 100% ASR, revisar grafia de marcas "
                 "antes de gerar motions")
    lines += ["", "## Blocos"]
    for b in blocks:
        text = " ".join(w["word"] for w in b.get("words", []))
        lines.append(f"{_fmt_time(b['start'])} → {_fmt_time(b['end'])}  {text}")
        for tela in b.get("telas", []):
            lines.append(f"TELA: {tela}")
    div = divergent_blocks(blocks) if copy_ref else []
    if div:
        lines += ["", "## Divergências (revisar se necessário)"]
        for i in div:
            text = " ".join(w["word"] for w in blocks[i - 1]["words"])
            lines.append(f'- bloco {i}: maioria sem correspondência na copy '
                        f'("{text}")')
    return "\n".join(lines) + "\n"
