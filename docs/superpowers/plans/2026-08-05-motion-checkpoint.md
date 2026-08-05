# Motion Checkpoint (handoff corte→motions) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Motions passam a nascer do corte aprovado: novo handoff (transcript do corte + copy do vault) alimenta o MotionSkills; `--somente-corte` deixa de exigir manifest.

**Architecture:** Núcleo puro em `src/motion_handoff.py` (parse da copy, merge falado-é-verdade, blocos, âncoras TELA, formatação) + CLI `src/prepare_motion_handoff.py` (lê timeline via MCP ou cutlist). `compose_premiere.py` ganha molde de sequência gerado por ffmpeg quando não há manifest. Skills (`rough-cut` no EditorClaude, `transcript-to-motion` no MotionSkills) documentam o fluxo novo.

**Tech Stack:** Python 3.11 (venv `.venv`), difflib.SequenceMatcher, ffmpeg lavfi, Premiere MCP (ExtendScript via bridge), testes standalone sem pytest.

**Spec:** `docs/superpowers/specs/2026-08-04-motion-checkpoint-design.md` (aprovado).

> **STATUS DE EXECUÇÃO (2026-08-05):** Tasks 1–3 executadas e revisadas. Os
> blocos de código da Task 1 foram sincronizados com os fixes de review; os
> das Tasks 2–3 NÃO — o repo é a verdade (commits `536dd11..bd819c9` contêm
> fixes de review por cima: `_fmt_time` arredonda antes de fatiar, divergência
> só existe quando há copy, mkdir do --out, sort defensivo, removeprefix).
> Quem reexecutar o plano do zero deve preferir o código do repo aos blocos
> das Tasks 2–3. Coordenação com o plano irmão: ver
> `2026-08-05-fundacao-2cerebro-pipeline-checkpoint.md` (seção COORDENAÇÃO).

**Convenções deste repo (obrigatórias):**
- Testes rodam com `.venv/bin/python tests/<arquivo>.py` — sem pytest.
- Commits direto na `main`, mensagens em pt-BR no estilo do log (`Handoff: ...`), push após cada bloco commitado (remote `lfelipebessa/editorClaude`).
- `output/` é gitignored; nunca commitar vídeo/artefato grande.
- Docstrings/comentários em pt-BR, estilo dos módulos existentes.

**Decisão de design que NÃO está no spec (registrada no brainstorm):** o
`merge_corrected_text` das legendas trata o texto corrigido como verdade e
**descarta** palavra falada sem par (opcode `delete` não emite). Para o handoff
a verdade é o FALADO — por isso o núcleo ganha `merge_with_copy` (variante que
mantém palavra sem par como o ASR ouviu, com proveniência), em vez de reusar
`merge_corrected_text`. `compose.py` não muda.

---

## Task 1: Núcleo — `parse_copy` + `merge_with_copy`

**Files:**
- Create: `src/motion_handoff.py`
- Create: `tests/test_handoff.py`

- [ ] **Step 1: Write the failing tests**

Criar `tests/test_handoff.py`:

```python
"""Testes do núcleo do handoff de motions (motion_handoff.py).

Rodar: .venv/bin/python tests/test_handoff.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from motion_handoff import merge_with_copy, parse_copy


def W(word, start, end, clip=0):
    return {"word": word, "start": start, "end": end, "clip": clip}


def test_merge_grafia_vem_da_copy():
    words = [W("cloud", 0.0, 0.4), W("code", 0.5, 0.9), W("resolve", 1.0, 1.5)]
    copy = [{"text": "Claude Code resolve"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["Claude", "Code", "resolve"], out
    assert out[0]["start"] == 0.0 and out[1]["end"] == 0.9, "timing é do falado"
    assert all(w["matched"] for w in out), out


def test_merge_improviso_fica_como_asr():
    words = [W("isso", 0.0, 0.3), W("aqui", 0.4, 0.7), W("é", 0.8, 0.9),
             W("surreal", 1.0, 1.5), W("demais", 1.6, 2.0)]
    copy = [{"text": "isso aqui"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["isso", "aqui", "é", "surreal",
                                       "demais"], out
    assert [w["matched"] for w in out] == [True, True, False, False, False]


def test_merge_copy_nao_falada_nao_entra():
    words = [W("comenta", 0.0, 0.4), W("reunião", 0.5, 1.0)]
    copy = [{"text": "comenta reunião que eu te mando o link"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["comenta", "reunião"], out


def test_merge_sem_copy_marca_tudo_nao_casado():
    words = [W("oi", 0.0, 0.3)]
    out = merge_with_copy(words, [])
    assert out[0]["word"] == "oi" and out[0]["matched"] is False


def test_merge_palavra_nao_falada_nunca_entra_mesmo_em_replace():
    # regressão: "eu" da copy não pode substituir "terminei"/"a"/"call" só
    # porque o alinhamento global jogou os dois lados no mesmo opcode.
    words = [W("terminei", 0.0, 0.4), W("a", 0.5, 0.6), W("call", 0.7, 1.0)]
    copy = [{"text": "eu"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["terminei", "a", "call"], out
    assert [w["matched"] for w in out] == [False, False, False], out


def test_merge_marca_partida_colapsa_com_timing_do_span():
    words = [W("chat", 0.0, 0.4), W("gpt", 0.4, 0.9)]
    copy = [{"text": "ChatGPT"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["ChatGPT"], out
    assert out[0]["matched"] is True
    assert out[0]["start"] == 0.0 and out[0]["end"] == 0.9, out


def test_merge_grafia_parecida_continua_corrigindo():
    words = [W("cloud", 0.0, 0.4)]
    copy = [{"text": "Claude"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["Claude"], out
    assert out[0]["matched"] is True


def test_parse_copy_ignora_frontmatter_heading_timestamp():
    md = ("---\ntipo: ideia\nstatus: trabalhada\n---\n"
          "# Gancho\n"
          "0:00 → 0:07 Eu não entro mais em call sem isso\n"
          "TELA: **MEETILY**\n"
          "[00:19] Roda tudo local\n")
    chunks, telas = parse_copy(md)
    text = chunks[0]["text"]
    assert "Eu não entro mais em call sem isso" in text, text
    assert "Roda tudo local" in text, text
    assert "0:00" not in text and "00:19" not in text, text
    assert "MEETILY" not in text, "TELA não é prosa"
    assert len(telas) == 1 and telas[0]["text"] == "**MEETILY**", telas
    assert telas[0]["anchor"] == ["mais", "em", "call", "sem", "isso"], telas


def test_parse_copy_vazia():
    chunks, telas = parse_copy("---\ntipo: ideia\n---\n")
    assert chunks == [] and telas == []


def test_parse_copy_tela_variantes():
    md = ("**TELA:** MEETILY\n"
          "isso aqui\n"
          "- TELA: OUTRA\n"
          "tela: TERCEIRA\n"
          "> TELA: QUARTA\n")
    chunks, telas = parse_copy(md)
    assert [t["text"] for t in telas] == ["MEETILY", "OUTRA", "TERCEIRA",
                                          "QUARTA"], telas
    assert "TELA" not in chunks[0]["text"], chunks
    assert "MEETILY" not in chunks[0]["text"], chunks


def test_parse_copy_limpa_markdown_da_prosa():
    md = "o **Meetily** roda\nuso o [[Claude Code]] direto\n"
    chunks, telas = parse_copy(md)
    text = chunks[0]["text"]
    assert "**" not in text and "[[" not in text and "]]" not in text, text
    assert text.split() == ["o", "Meetily", "roda", "uso", "o", "Claude",
                            "Code", "direto"], text


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} testes passaram")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/luizfelipebessa/development/EditorClaude && .venv/bin/python tests/test_handoff.py`
Expected: `ModuleNotFoundError: No module named 'motion_handoff'`

- [ ] **Step 3: Write minimal implementation**

Criar `src/motion_handoff.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python tests/test_handoff.py`
Expected: `11 testes passaram`

- [ ] **Step 5: Commit**

```bash
git add src/motion_handoff.py tests/test_handoff.py
git commit -m "Handoff: núcleo parse_copy + merge_with_copy (falado é a verdade, copy corrige grafia)"
```

---

## Task 2: Núcleo — blocos, âncoras TELA e formatação

**Files:**
- Modify: `src/motion_handoff.py` (append)
- Modify: `tests/test_handoff.py` (append)

- [ ] **Step 1: Write the failing tests**

Acrescentar em `tests/test_handoff.py`, antes do bloco `if __name__` (e
ampliar o import no topo):

```python
from motion_handoff import (anchor_telas, assign_words, build_blocks,
                            format_handoff, merge_with_copy, parse_copy)
```

```python
def test_build_blocks_funde_curto_com_seguinte():
    bounds = [(0.0, 1.0), (1.0, 3.0), (3.0, 3.8)]
    blocks = build_blocks(bounds, min_dur=1.5)
    # (0,1.0) é curto -> funde com o seguinte; sobra final curta -> anterior
    assert [(b["start"], b["end"]) for b in blocks] == [(0.0, 3.8)], blocks


def test_build_blocks_sem_fusao():
    bounds = [(0.0, 2.0), (2.0, 5.5)]
    blocks = build_blocks(bounds, min_dur=1.5)
    assert [(b["start"], b["end"]) for b in blocks] == [(0.0, 2.0),
                                                        (2.0, 5.5)], blocks


def test_assign_words_pertence_pelo_inicio():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("a", 0.1, 0.4), W("b", 1.9, 2.3), W("c", 2.5, 3.0)]
    assign_words(blocks, words)
    assert [w["word"] for w in blocks[0]["words"]] == ["a", "b"]
    assert [w["word"] for w in blocks[1]["words"]] == ["c"]


def test_anchor_tela_cai_no_bloco_do_trecho():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("call", 0.2, 0.5), W("sem", 0.6, 0.8), W("isso", 0.9, 1.2),
             W("roda", 2.1, 2.4), W("tudo", 2.5, 2.8), W("local", 2.9, 3.3)]
    telas = [{"text": "**MEETILY**", "anchor": ["roda", "tudo", "local"]}]
    anchor_telas(telas, words, blocks)
    assert blocks[1].get("telas") == ["**MEETILY**"], blocks
    assert "telas" not in blocks[0]


def test_anchor_tela_sem_ancora_vai_pro_primeiro_bloco():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("oi", 0.1, 0.3)]
    telas = [{"text": "**ABRE**", "anchor": []}]
    anchor_telas(telas, words, blocks)
    assert blocks[0].get("telas") == ["**ABRE**"]


def test_format_handoff_cabecalho_blocos_divergencia():
    blocks = [{"start": 0.0, "end": 2.0,
               "words": [{**W("Claude", 0.1, 0.5), "matched": True},
                         {**W("Code", 0.6, 1.0), "matched": True}],
               "telas": ["**MEETILY**"]},
              {"start": 2.0, "end": 4.0,
               "words": [{**W("improviso", 2.1, 2.6), "matched": False},
                         {**W("total", 2.7, 3.2), "matched": False}]}]
    md = format_handoff("meetily", blocks, "Copy Meetily")
    assert md.startswith("# Handoff — meetily  (v1)\n"), md
    assert "Fonte: corte aprovado (EditorClaude) · Corte: 4.0s · Blocos: 2" in md
    assert "Copy: [[Copy Meetily]]" in md
    assert "0:00.0 → 0:02.0  Claude Code" in md, md
    assert "TELA: **MEETILY**" in md
    assert "## Divergências" in md and "bloco 2" in md, md


def test_format_handoff_sem_copy_avisa():
    blocks = [{"start": 0.0, "end": 2.0,
               "words": [{**W("oi", 0.1, 0.5), "matched": False}]}]
    md = format_handoff("x", blocks, None)
    assert "Copy: NENHUMA" in md, md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python tests/test_handoff.py`
Expected: `ImportError: cannot import name 'anchor_telas'`

- [ ] **Step 3: Write minimal implementation**

Acrescentar ao fim de `src/motion_handoff.py`:

```python
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
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


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
    div = divergent_blocks(blocks)
    if div:
        lines += ["", "## Divergências (revisar se necessário)"]
        for i in div:
            text = " ".join(w["word"] for w in blocks[i - 1]["words"])
            lines.append(f'- bloco {i}: sem correspondência na copy ("{text}")')
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python tests/test_handoff.py`
Expected: `18 testes passaram`

- [ ] **Step 5: Commit**

```bash
git add src/motion_handoff.py tests/test_handoff.py
git commit -m "Handoff: blocos (fusão <1.5s), reancoragem de TELA e formatação com divergências"
```

---

## Task 3: CLI `src/prepare_motion_handoff.py`

**Files:**
- Create: `src/prepare_motion_handoff.py`

Sem teste unitário próprio: o núcleo já está coberto e o CLI é I/O + MCP;
a validação é a golden run da Task 6 (cutlist real do meetily).

- [ ] **Step 1: Write the CLI**

```python
"""Gera o handoff de motions a partir do corte APROVADO — o passo novo entre
o checkpoint de corte e a geração no MotionSkills (spec 2026-08-04).

Uso:
    python src/prepare_motion_handoff.py output/transcript_<slug>.json \
        --copy "/caminho/da/nota-de-copy.md" \
        --sequence-name reel_<slug> [--media-name dji_] [--camera-track 1]
    # fallback sem Premiere aberto (reflete o corte AUTOMÁTICO):
    python src/prepare_motion_handoff.py output/transcript_<slug>.json \
        --copy "..." --cutlist output/cutlist_<slug>.json

Saída: output/handoff_<slug>.md — blocos com tempo real do corte + texto
mesclado com a copy (grafia dela, conteúdo do falado) + TELA: reancorados +
seção Divergências. Enviar ao Produtor de Video do MotionSkills via Maestri.
"""

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_ROOT / "adapters"))  # render_ffmpeg (import indireto)
sys.path.insert(0, str(_ROOT / "adapters" / "premiere_mcp"))

from compose import remap_words, remap_words_by_clips
from motion_handoff import (anchor_telas, assign_words, build_blocks,
                            divergent_blocks, format_handoff,
                            merge_with_copy, parse_copy)


def read_timeline_bounds(sequence_name: str, camera_track: int,
                         media_name: str, timeout: float) -> list[dict]:
    """Clipes de câmera da timeline (posição real pós-edição manual)."""
    from finalize_premiere import read_camera_clips
    from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY,
                                 MCPStdioClient)
    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=timeout)
    client.start()
    try:
        seqs = client.call_tool("list_sequences", {})
        seq_id = next((s["id"] for s in seqs.get("sequences", [])
                       if s.get("name") == sequence_name), None)
        if not seq_id:
            sys.exit(f"sequência {sequence_name!r} não encontrada")
        client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})
        return read_camera_clips(client, camera_track, media_name)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--copy", type=Path, default=None,
                        help="nota de copy no vault (markdown)")
    parser.add_argument("--sequence-name", default=None,
                        help="lê o corte REAL da timeline (padrão do fluxo)")
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--cutlist", type=Path, default=None,
                        help="fallback sem Premiere: corte automático")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-block", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not args.sequence_name and not args.cutlist:
        sys.exit("informe --sequence-name (timeline) ou --cutlist (fallback)")
    if not args.transcript.exists():
        sys.exit(f"não encontrado: {args.transcript}")

    slug = args.transcript.stem.replace("transcript_", "")
    out_path = args.out or Path(f"output/handoff_{slug}.md")

    transcript = json.loads(args.transcript.read_text())
    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]

    if args.sequence_name:
        clips = read_timeline_bounds(args.sequence_name, args.camera_track,
                                     args.media_name, args.timeout)
        out_words = remap_words_by_clips(words, clips)
        bounds = [(round(c["start"], 3), round(c["end"], 3)) for c in clips]
    else:
        if not args.cutlist.exists():
            sys.exit(f"não encontrado: {args.cutlist}")
        print("AVISO: handoff a partir da CUTLIST — reflete o corte "
              "automático, não o ajuste manual da timeline.")
        cutlist = json.loads(args.cutlist.read_text())
        out_words = remap_words(words, cutlist["segments"])
        bounds, off = [], 0.0
        for s in cutlist["segments"]:
            dur = s["end"] - s["start"]
            bounds.append((round(off, 3), round(off + dur, 3)))
            off += dur
    if not out_words:
        sys.exit("nenhuma palavra sobreviveu ao remap — "
                 "transcript e corte batem?")

    chunks, telas, copy_ref = [], [], None
    if args.copy and args.copy.exists():
        chunks, telas = parse_copy(args.copy.read_text())
        copy_ref = args.copy.stem
    else:
        origem = f"copy não encontrada ({args.copy})" if args.copy \
            else "sem --copy"
        print(f"AVISO: {origem} — texto 100% ASR, REVISAR grafia de marcas "
              "no handoff antes do envio.")

    merged = merge_with_copy(out_words, chunks)
    blocks = build_blocks(bounds, min_dur=args.min_block)
    assign_words(blocks, merged)
    anchor_telas(telas, merged, blocks)
    out_path.write_text(format_handoff(slug, blocks, copy_ref))

    div = divergent_blocks(blocks)
    total = blocks[-1]["end"] if blocks else 0.0
    print(f"handoff: {out_path} ({len(blocks)} blocos, {total:.1f}s, "
          f"{len(telas)} TELA, {len(div)} divergentes)")
    if div:
        print("divergências marcadas no arquivo — envio segue automático, "
              "relatório vai junto para o produtor.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test do argparse e dos imports**

Run: `.venv/bin/python src/prepare_motion_handoff.py --help`
Expected: usage com `--copy`, `--sequence-name`, `--cutlist` (exit 0)

Run: `.venv/bin/python src/prepare_motion_handoff.py output/nao_existe.json --cutlist output/x.json`
Expected: `não encontrado: output/nao_existe.json` (exit != 0)

- [ ] **Step 3: Commit**

```bash
git add src/prepare_motion_handoff.py
git commit -m "Handoff: CLI prepare_motion_handoff (timeline via MCP ou cutlist fallback)"
```

---

## Task 4: `compose_premiere.py --somente-corte` sem manifest

**Files:**
- Modify: `adapters/premiere_mcp/compose_premiere.py`

Hoje o modo corte exige o manifest e TODOS os clips renderizados (valida em
`main()`), e usa `scenes[0]["clip"]` como molde de formato da sequência. No
fluxo novo não existem clips na ETAPA CORTE.

- [ ] **Step 1: Adicionar `ensure_mold_clip`**

No topo do arquivo, garantir os imports (conferir os existentes antes —
`subprocess` e `FFMPEG` provavelmente faltam):

```python
import subprocess
from render_ffmpeg import FFMPEG  # junto dos imports de render_ffmpeg já existentes
```

Adicionar a função perto de `import_item` (nível de módulo):

```python
def ensure_mold_clip(w: int, h: int, fps: int) -> Path:
    """Clipe preto de 1s usado só como molde de formato da sequência —
    create_sequence abriria o diálogo modal New Sequence, então a sequência
    precisa nascer de um clipe (dança validada do render_premiere). Gerado
    uma vez em output/ (gitignored)."""
    mold = (Path(__file__).resolve().parent.parent.parent
            / "output" / f"mold_{w}x{h}_{fps}.mp4")
    if not mold.exists():
        mold.parent.mkdir(exist_ok=True)
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r={fps}",
             "-t", "1", "-pix_fmt", "yuv420p", str(mold)], check=True)
    return mold
```

- [ ] **Step 2: Molde no lugar de `scenes[0]` no modo corte**

Em `compose()`, trocar o branch `if somente_corte:` da importação de mídia:

```python
        if somente_corte:
            # etapa 1: só câmera + voz; um clipe-molde preto dá o formato da
            # sequência (1080x1920 @30) — clips de motion ainda não existem,
            # nascem do corte aprovado (spec 2026-08-04).
            print("importando mídia (etapa CORTE: câmera + molde de formato)...")
            cam_id = import_item(client, video)
            mg_ids = [import_item(client, ensure_mold_clip(
                seq_w, seq_h, layout.get("fps", 30)))]
            srt_id = None
```

(`seq_w`/`seq_h` já são calculados acima com defaults 1080x1920.)

- [ ] **Step 3: Manifest opcional no `main()`**

Trocar `parser.add_argument("manifest", type=Path)` por:

```python
    parser.add_argument("manifest", type=Path, nargs="?", default=None,
                        help="opcional com --somente-corte (clips ainda não existem)")
```

E ajustar as validações/carga logo abaixo (o loop de existência e o
`json.loads`):

```python
    if args.manifest is None and not args.somente_corte:
        sys.exit("manifest é obrigatório fora de --somente-corte")
    for p in (args.video, args.cutlist) + \
            ((args.manifest,) if args.manifest else ()):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    if args.srt and not args.srt.exists():
        sys.exit(f"SRT não encontrado: {args.srt}")
    cutlist = json.loads(args.cutlist.read_text())
    manifest = (json.loads(args.manifest.read_text()) if args.manifest
                else {"scenes": [], "layout": {}})
    if not args.somente_corte:
        for sc in manifest["scenes"]:
            if not Path(sc["clip"]).exists():
                sys.exit(f"clipe de motion não encontrado: {sc['clip']}")
```

- [ ] **Step 4: Verificar sintaxe e ajuda**

Run: `.venv/bin/python -m py_compile adapters/premiere_mcp/compose_premiere.py && .venv/bin/python adapters/premiere_mcp/compose_premiere.py --help`
Expected: usage mostrando `[manifest]` como opcional (exit 0)

Run: `.venv/bin/python adapters/premiere_mcp/compose_premiere.py video.mp4 output/cutlist.json 2>&1 | head -2`
Expected: `manifest é obrigatório fora de --somente-corte` (não é regressão:
sem --somente-corte o manifest continua exigido)

- [ ] **Step 5: Rodar os testes existentes (regressão)**

Run: `.venv/bin/python tests/test_cutlist.py && .venv/bin/python tests/test_handoff.py`
Expected: todos passam

- [ ] **Step 6: Commit**

```bash
git add adapters/premiere_mcp/compose_premiere.py
git commit -m "Compose Premiere: --somente-corte dispensa manifest (molde de sequência via ffmpeg lavfi)"
```

---

## Task 5: Skill `rough-cut` — fluxo novo do 3b + arquivamento no vault

**Files:**
- Modify: `.claude/skills/rough-cut/SKILL.md` (passo 3b)

- [ ] **Step 1: Reescrever a introdução do 3b**

Substituir o parágrafo de abertura do 3b (de "quando existir dir do vídeo no
MotionSkills" até "FORMATO PADRÃO do Reel: motions em cima, câmera embaixo,
legendas na divisa.") por:

```markdown
3b. **Reel composto com motion graphics** — FORMATO PADRÃO do Reel do canal:
   motions em cima, câmera embaixo, legendas na divisa. Desde 2026-08-05 os
   motions NASCEM DO CORTE APROVADO (spec 2026-08-04-motion-checkpoint): não
   existe mais gerar motion da copy antes da gravação — o dir do vídeo no
   MotionSkills é criado no meio deste fluxo, a partir do handoff.
```

- [ ] **Step 2: Substituir a sequência numerada do 3b**

Substituir o parágrafo "Metodologia em ETAPAS..." e o bloco de comandos
(itens 1–8 atuais) por:

```markdown
   **Metodologia em ETAPAS com checkpoints do usuário (padrão desde
   2026-07-31; handoff desde 2026-08-05): CORTE → checkpoint → HANDOFF →
   geração no MotionSkills (paralela) → MOTIONS+MÚSICA → checkpoint + cor
   manual → LEGENDAS por último.** O corte automático sempre precisa de
   ajuste fino humano, e legenda por último absorve qualquer retoque:

   ```bash
   # 1. ETAPA CORTE: timeline só com câmera + voz, SEM manifest (clips de
   #    motion ainda não existem — V1 vazia -> Close Gap funciona)
   .venv/bin/python adapters/premiere_mcp/compose_premiere.py <video> output/cutlist_<slug>.json --sequence-name reel_<slug> --somente-corte
   # 2. CHECKPOINT: usuário edita o corte e avisa quando fechou
   # 3. HANDOFF (corte aprovado -> MotionSkills): lê o corte FINAL da
   #    timeline, mescla com a copy do vault (grafia + TELA:) e gera
   #    output/handoff_<slug>.md
   .venv/bin/python src/prepare_motion_handoff.py output/transcript_<slug>.json --copy "<nota de copy no 2Cerebro>" --sequence-name reel_<slug>
   #    -> na nota de copy do vault: frontmatter ganha status:
   #       entregue-ao-pipeline e o slug (campos que o template já prevê)
   #    -> enviar o handoff (com o relatório de Divergências) ao Produtor
   #       de Video do MotionSkills via Maestri; agente DESSELECIONADO no
   #       canvas; geração (brief -> cenas -> render) roda em paralelo —
   #       seguir o fluxo quando os clips chegarem (maestri notify)
   # 4. cola (SÓ depois dos clips chegarem): manifest resolvido + SRT
   .venv/bin/python src/prepare_compose.py output/transcript_<slug>.json output/cutlist_<slug>.json ~/development/MotionSkills/motion-graphics/src/videos/<nome>
   # 5. REVISAR o SRT contra o HANDOFF (transcrição erra: cloud->Claude,
   #    admira->ADMIN...) — corrigir SÓ texto, nunca timestamps
   # 6. ETAPA MOTIONS: lê o corte FINAL da timeline e sobe motions fatiados
   #    nos cortes reais + música aparada ao fim do conteúdo + punch-in de
   #    abertura automático (1º clipe da câmera E do motion abrem em Scale
   #    120 ABSOLUTO assentando na base de cada um em 0.4s, blur só na
   #    câmera — seção punch_in do style)
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa motions
   # 7. CHECKPOINT: usuário revisa o dinamismo; COR entra aqui, manual:
   #    Paste Attributes da referência em V2 (NUNCA marcar Motion/Crop)
   # 8. ETAPA LEGENDAS (sempre a última — lê o áudio ATUAL da timeline):
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa legendas --corrected-srt output/captions_<slug>.srt
   # 9. QA DA LEGENDA (sempre rodar após a etapa legendas): re-transcreve o
   #    áudio do corte final e diffa com a legenda — pega frase que o ASR
   #    ENGOLIU no bruto (ex.: "Terminei a call" virou a palavra falsa "Eu";
   #    palavra que não existe no transcript nunca vira legenda). Diff tem
   #    ruído em borda de corte; sinal forte = os dois ASRs discordando da
   #    MESMA região. Frase engolida: inserir palavras no transcript (com os
   #    timestamps de fonte que o QA imprime), tokens no SRT corrigido, e
   #    refazer com recaption.
   .venv/bin/python adapters/premiere_mcp/qa_captions_premiere.py <video> output/captions_reel_<slug>_final.srt --sequence-name reel_<slug>
   # 10. ARQUIVAR NO VAULT (fecha o ciclo com o 2Cerebro): nota de resultado
   #    seguindo 98 Templates/ e 99 Contexto/arquitetura-do-vault.md — NUNCA
   #    inventar estrutura nova. A nota linka [[copy]], traz o transcript
   #    real do corte (texto corrido dos blocos do handoff), o brief e os
   #    caminhos dos artefatos locais. Métrica NÃO entra (é assunto do
   #    EstudoConteudo/Supabase — regra do template).
   ```
```

(Manter intocados os parágrafos seguintes do 3b: `--etapa tudo`, recaption,
mp4 automático, "Motion entra exatamente como autorado", música, 3c etc.)

- [ ] **Step 3: Revisar o diff**

Run: `git diff .claude/skills/rough-cut/SKILL.md | head -100`
Expected: intro + sequência renumerada 1–10; itens 6–9 idênticos aos antigos
5–8 fora da numeração; nada removido dos parágrafos posteriores.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/rough-cut/SKILL.md
git commit -m "rough-cut: motions nascem do corte aprovado — handoff no 3b + arquivamento no vault"
```

---

## Task 6: Golden run com dados reais do meetily

**Files:**
- Nenhum novo (validação; `output/` é gitignored)

- [ ] **Step 1: Gerar handoff do meetily (modo cutlist, sem copy)**

Run: `.venv/bin/python src/prepare_motion_handoff.py output/transcript_meetily.json --cutlist output/cutlist_meetily.json`
Expected: AVISO de cutlist + AVISO de sem copy; `handoff: output/handoff_meetily.md (N blocos, ~37s...)` — sem traceback.

- [ ] **Step 2: Validar invariantes estruturais do handoff**

Run: `cat output/handoff_meetily.md`

ATENÇÃO (corrigido na review da Task 2): NÃO comparar inícios de bloco com os
starts do `motion_manifest_meetily.json` — aqueles vieram do
`find_scene_starts` ancorando em palavra no MEIO de clipe (fluxo velho,
copy→fuzzy) e não podem coincidir com fronteira de bloco; no fluxo novo a
causalidade inverte (o MotionSkills escolhe cenas A PARTIR dos blocos).
Critérios que validam de verdade (já medidos verdes no dado real na review):
- blocos ladrilham o corte inteiro sem gap/overlap (0.000 → 40.023 no meetily);
- nenhuma palavra do remap se perde (179 → 179 no meetily);
- nenhum bloco com duração < min_dur (1.5s);
- granularidade suficiente para 3–8 cenas (15 blocos no meetily);
- leitura humana: texto dos blocos é o falado real; TELA e Divergências
  fazem sentido.

- [ ] **Step 3: Corrigir o que a golden run revelar**

Se algum invariante falhar, debugar `build_blocks`/`remap_words` com
o dado real antes de seguir (systematic-debugging). Commitar o fix com teste
novo em `tests/test_handoff.py` reproduzindo o caso.

- [ ] **Step 4: Push do bloco EditorClaude**

```bash
git push
```

---

## Task 7: Skill `transcript-to-motion` — fonte handoff (repo MotionSkills)

**Files:**
- Modify: `/Users/luizfelipebessa/development/MotionSkills/motion-graphics/.claude/skills/transcript-to-motion/SKILL.md`

Este task roda no repo MotionSkills. Ler o SKILL.md inteiro antes de editar
(as seções citadas: detecção de formato ~linhas 12–17, duração ~32–36, brief
~69–84 — podem ter mudado).

- [ ] **Step 1: Adicionar `handoff` à detecção de formato**

Na lista de formatos de entrada (junto de timestamped/plain/mixed),
acrescentar:

```markdown
- **handoff** — arquivo com cabeçalho `Fonte: corte aprovado (EditorClaude)`
  (gerado pelo prepare_motion_handoff.py): blocos `m:ss.s → m:ss.s` com
  tempos REAIS do corte final, marcadores `TELA:` e seção `## Divergências`.
  Tem precedência sobre a detecção timestamped comum.
```

- [ ] **Step 2: Regras de duração para handoff**

Logo após a regra de duração atual (fala +20%, mínimo 3s, master ×1,2 em
blocos de 5s), acrescentar:

```markdown
**Quando a fonte é handoff, os tempos são EXATOS — as regras de estimativa
não se aplicam:**
- Sem 150wpm, sem +20%, sem arredondar master para blocos de 5s: master =
  duração exata do corte; cada cena = soma exata dos seus blocos.
- Fronteira de cena SÓ em fronteira de bloco do handoff (o bloco é a menor
  unidade; 3–8 cenas continuam valendo).
- O texto do handoff é o que o usuário realmente FALOU (a seção Divergências
  só marca onde a copy não bateu) — usar como está, nunca "corrigir" de
  volta para a copy.
- `brief.md` registra `Fonte: handoff (corte aprovado <slug>)`.
- Cenas Loop continuam permitidas, mas não existe sobra de master a absorver.
```

- [ ] **Step 3: Commit no repo MotionSkills**

```bash
cd /Users/luizfelipebessa/development/MotionSkills/motion-graphics
git add .claude/skills/transcript-to-motion/SKILL.md
git commit -m "transcript-to-motion: fonte handoff (tempos exatos do corte aprovado do EditorClaude)"
git remote -v | grep -q origin && git push || echo "sem remote, só commit local"
```

---

## Self-review (feito na escrita do plano)

- **Spec coverage:** handoff script (Tasks 1–3), somente-corte sem manifest
  (Task 4), rough-cut + vault I/O (Task 5), golden meetily (Task 6, teste do
  spec), transcript-to-motion (Task 7). `prepare_compose` sem mudança
  (decisão do spec). Sanidade manual MotionSkills (brief do meetily vs
  existente) fica a critério do usuário após Task 7 — exige sessão agentic
  no outro repo, não é automatizável daqui.
- **Types:** `merge_with_copy` retorna words com `matched`; `assign_words`
  preenche `blocks[i]["words"]`; `format_handoff`/`divergent_blocks` leem
  esses campos — nomes conferidos entre Tasks 1–3.
- **Placeholders:** nenhum TBD; todos os comandos com saída esperada.
