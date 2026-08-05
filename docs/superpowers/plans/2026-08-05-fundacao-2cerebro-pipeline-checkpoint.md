# Fundação 2Cerebro + Pipeline de Vídeo com Checkpoint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plugar todos os projetos de `~/development` no vault 2Cerebro por um CLAUDE.md guarda-chuva, e fazer o pipeline de vídeo gerar motion graphics da fala REAL do corte aprovado (persistida em artefatos no checkpoint 1), com diff copy×fala como trava pré-publicação.

**Architecture:** Abordagem "córtex e membros" — vault só conhecimento, repos intocados (contrato via CLAUDE.md de diretório pai). No EditorClaude, o checkpoint 1 (que já existe) passa a persistir `cutlist_final_<slug>.json` + `transcript_cut_<slug>.json` + `transcript_cut_<slug>.md`; o MotionSkills autora o brief sobre esse `.md` (modo real: durações exatas, sem +20%); o diff copy×fala roda no checkpoint 2 antes de publicar. Spec completa: vault `03 Recursos/Técnico/Design — Fundação do 2Cerebro e pipeline de vídeo com checkpoint.md`.

**Tech Stack:** Python 3.11 (stdlib only nas peças novas), testes standalone (padrão do repo, sem pytest), Premiere via MCP bridge existente, Remotion/skill no MotionSkills (só markdown), ffmpeg.

**Convenções deste repo (EditorClaude):**
- Rodar tudo do diretório do projeto com `.venv/bin/python`.
- Testes são scripts standalone: `.venv/bin/python tests/test_x.py` imprime `OK` no fim.
- `output/` é gitignored — artefatos de teste com dados reais usam `tempfile`.
- Commits pequenos, mensagem em português como o histórico do repo.

**Caminhos absolutos usados no plano:**
- EditorClaude: `~/development/EditorClaude`
- MotionSkills: `~/development/MotionSkills/motion-graphics`
- Vault: `~/development/2Cerebro` (symlink; caminhos têm espaço — sempre entre aspas)

---

### Task 0: Branches de trabalho

**Files:** nenhum (só git)

- [ ] **Step 0.1:** Criar branch no EditorClaude:

```bash
cd ~/development/EditorClaude && git checkout -b fundacao-pipeline-checkpoint
```

- [ ] **Step 0.2:** Criar branch no MotionSkills:

```bash
cd ~/development/MotionSkills/motion-graphics && git checkout -b transcript-cut-real-mode
```

---

### Task 1: CLAUDE.md guarda-chuva em `~/development`

**Files:**
- Create: `~/development/CLAUDE.md`

O Claude Code herda CLAUDE.md de diretórios pais — este arquivo vale para toda sessão em qualquer repo sob `~/development`. Meia página, sem detalhe (detalhe mora no vault). `~/development` não é repo git — não há commit.

- [ ] **Step 1.1: Escrever o arquivo** com exatamente este conteúdo:

```markdown
# Contexto comum — todos os projetos em ~/development

## Contexto canônico (ler, nunca copiar)

Posicionamento, audiência e regras duras vivem no vault 2Cerebro — fonte única:
`~/development/2Cerebro/99 Contexto/` (`contexto-luiz.md`, `posicionamento.md`,
`audiencia.md`, `regras-duras.md`). Antes de qualquer decisão criativa ou de
negócio (copy, citação de cliente, tom, público-alvo), Read os arquivos
relevantes de lá. Nunca colar o conteúdo em outro lugar — sempre apontar.

## Destilação pro vault (fim de sessão)

Se a sessão produziu algo relevante, devolver ao vault (`~/development/2Cerebro/`),
seguindo os templates de `98 Templates/`:

- aprendizado técnico reutilizável → `03 Recursos/Técnico/`
- entrega/resultado de cliente → `04 Casos/` (template `Caso.md`)
- copy publicada → `03 Recursos/Swipe/Minhas copies/`
- registrar a operação: append no TOPO de `99 Contexto/log.md`
  (formato `## [YYYY-MM-DD] tipo | título`)

Travas (inegociáveis): tudo que agente cria nasce `rascunho: true` e
`pode_citar_nome: false` — só o Luiz promove. Proibido escrever em
`99 Contexto/` (exceção única: o append no log) e em `.obsidian/`. Proibido
copiar métrica de vídeo/Supabase pro vault — só conclusão qualitativa em
português. Resultado sem evidência = `⚠️ A PREENCHER`, nunca inventar.

## Exceções por repo

| Repo | Regra |
|---|---|
| Addept, SalesDever | destilar normalmente, mas TUDO nasce com `usar_em_conteudo: false` no frontmatter (decisão 2026-07-29 — nada dessa era vira conteúdo) |
| 2Cerebro | é o próprio vault — vale o CLAUDE.md dele, não este arquivo |
```

- [ ] **Step 1.2: Verificar herança** — rodar de dentro de um repo sem CLAUDE.md próprio:

```bash
cd ~/development/Nexor && claude -p "Segundo as instruções deste projeto: pra onde vai um aprendizado técnico no fim da sessão, e com que frontmatter ele nasce? Responda em 1 linha."
```

Expected: resposta mencionando `03 Recursos/Técnico` e `rascunho: true` (prova que o guarda-chuva carregou). Se a resposta não mencionar, o arquivo não está sendo herdado — verificar nome/caminho exatos.

---

### Task 2: Molde de formato + manifest opcional no `--somente-corte`

**Files:**
- Create: `~/development/EditorClaude/assets/molde_1080x1920.mp4` (gerado por ffmpeg, ~5KB)
- Modify: `~/development/EditorClaude/adapters/premiere_mcp/compose_premiere.py` (função `compose` ~linhas 279-306 e `main` ~linhas 418-454)

No fluxo novo, na etapa CORTE ainda **não existe** brief/motion (o brief nasce depois, do transcript do corte). Mas `compose_premiere --somente-corte` usa `scenes[0]["clip"]` como molde 1080×1920 para criar a sequência (contorno do `create_sequence` bloqueado). Solução: molde estático + manifest opcional.

- [ ] **Step 2.1: Gerar o molde** (vídeo preto 2s, 1080×1920 @30fps — só formato importa):

```bash
cd ~/development/EditorClaude
ffmpeg -f lavfi -i color=c=black:s=1080x1920:r=30 -t 2 -pix_fmt yuv420p assets/molde_1080x1920.mp4
ffprobe -v error -show_entries stream=width,height,r_frame_rate -of csv=p=0 assets/molde_1080x1920.mp4
```

Expected: `1080,1920,30/1`

- [ ] **Step 2.2: Tornar manifest opcional em `compose()`** — editar o início da função (hoje `segments = cutlist["segments"]` ... `layout = manifest.get("layout", {})`):

```python
def compose(video: Path, cutlist: dict, manifest: dict | None, srt: Path | None,
            sequence_name: str, timeout: float,
            music_file: Path | None = None,
            music_cfg: dict | None = None,
            somente_corte: bool = False) -> None:
    segments = cutlist["segments"]
    total = round(sum(s["end"] - s["start"] for s in segments), 3)
    scenes = manifest["scenes"] if manifest else []
    layout = (manifest or {}).get("layout", {})
```

- [ ] **Step 2.3: Molde no ramo `somente_corte`** — trocar o bloco atual:

```python
        if somente_corte:
            # etapa 1: só câmera + voz; o molde entra apenas para dar o formato
            # 1080x1920 @30 à sequência. Motions/legenda/música sobem na etapa 2
            # (finalize_premiere), sincronizados ao corte FINAL do usuário.
            print("importando mídia (etapa CORTE: câmera + molde de formato)...")
            cam_id = import_item(client, video)
            molde = (Path(scenes[0]["clip"]) if scenes
                     else Path(__file__).resolve().parent.parent.parent
                     / "assets" / "molde_1080x1920.mp4")
            mg_ids = [import_item(client, molde)]
            srt_id = None
```

- [ ] **Step 2.4: `main()` — positional opcional e validações condicionais** — trocar `parser.add_argument("manifest", type=Path)` e o bloco de validação:

```python
    parser.add_argument("manifest", type=Path, nargs="?", default=None,
                        help="opcional com --somente-corte (fluxo do canal: o "
                             "brief nasce DEPOIS do corte, do transcript_cut)")
```

```python
    paths = [args.video, args.cutlist] + ([args.manifest] if args.manifest else [])
    for p in paths:
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    if args.manifest is None and not args.somente_corte:
        sys.exit("manifest é obrigatório sem --somente-corte")
    if args.srt and not args.srt.exists():
        sys.exit(f"SRT não encontrado: {args.srt}")
    cutlist = json.loads(args.cutlist.read_text())
    manifest = json.loads(args.manifest.read_text()) if args.manifest else None
    if manifest:
        for sc in manifest["scenes"]:
            if not Path(sc["clip"]).exists():
                sys.exit(f"clipe de motion não encontrado: {sc['clip']}")
```

- [ ] **Step 2.5: Smoke test sem Premiere** (só o parsing — a chamada MCP falharia sem bridge, então validar que o erro é de bridge, não de argparse):

```bash
cd ~/development/EditorClaude
.venv/bin/python adapters/premiere_mcp/compose_premiere.py output/transcript_dji_12x.json output/cutlist_dji_12x.json 2>&1 | head -3
```

Expected: `manifest é obrigatório sem --somente-corte` (transcript no lugar do vídeo não importa — a validação de manifest vem antes de abrir MCP). NÃO deve reclamar de argumento faltando.

- [ ] **Step 2.6: Rodar testes existentes do composer** (garantir que nada quebrou):

```bash
.venv/bin/python tests/test_compose_premiere.py && .venv/bin/python tests/test_compose.py
```

Expected: os dois imprimem OK (mesmo comportamento de antes da mudança).

- [ ] **Step 2.7: Commit**

```bash
git add assets/molde_1080x1920.mp4 adapters/premiere_mcp/compose_premiere.py
git commit -m "Etapa corte sem manifest: molde estático 1080x1920 (fluxo brief-depois-do-corte)"
```

---

### Task 3: `src/cut_artifacts.py` — persistência do corte (TDD)

**Files:**
- Create: `~/development/EditorClaude/src/cut_artifacts.py`
- Test: `~/development/EditorClaude/tests/test_cut_artifacts.py`

- [ ] **Step 3.1: Escrever o teste que falha:**

```python
"""Testes de cut_artifacts — roda direto: .venv/bin/python tests/test_cut_artifacts.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cut_artifacts import (cut_to_src, infer_speed_rate, offset_table,
                           remap_silences, remap_words_rich,
                           segments_from_clips, segments_from_cutlist,
                           write_cut_artifacts)

# --- sintético ---
segs = [{"src_start": 10.0, "src_end": 12.0}, {"src_start": 20.0, "src_end": 21.0}]
table = offset_table(segs)
assert table == [
    {"cut_start": 0.0, "cut_end": 2.0, "src_start": 10.0, "src_end": 12.0},
    {"cut_start": 2.0, "cut_end": 3.0, "src_start": 20.0, "src_end": 21.0}]
assert cut_to_src(0.5, table) == 10.5
assert cut_to_src(2.5, table) == 20.5
try:
    cut_to_src(9.9, table)
    assert False, "devia lançar ValueError fora do corte"
except ValueError:
    pass

words = [{"word": "Oi", "start": 10.1, "end": 10.4, "score": 0.9},
         {"word": "sumida", "start": 15.0, "end": 15.5, "score": 0.8},
         {"word": "tchau", "start": 20.2, "end": 20.6, "score": 0.7}]
rich = remap_words_rich(words, table)
assert [w["word"] for w in rich] == ["Oi", "tchau"]  # "sumida" foi cortada
assert rich[0]["score"] == 0.9 and rich[0]["src_start"] == 10.1
assert rich[1]["clip"] == 1 and rich[1]["start"] == 2.2

sil = remap_silences([{"start": 11.0, "end": 13.0}], table)
assert sil == [{"start": 1.0, "end": 2.0}]  # interseção com o trecho mantido

clips = [{"start": 5.0, "inPoint": 20.0, "outPoint": 21.0, "end": 6.0},
         {"start": 0.0, "inPoint": 10.0, "outPoint": 12.0, "end": 2.0}]
assert segments_from_clips(clips) == segs  # ordena pela posição na timeline

assert infer_speed_rate({"source": {"path": "/x/video_12x.mp4"}}, 1.2) == 1.2
assert infer_speed_rate({"source": {"path": "/x/video.mp4"}}, 1.2) == 1.0

# --- dados reais: os DOIS footages (dji_12x e meetily — requisito da spec) ---
root = Path(__file__).resolve().parent.parent
for tr_name, cl_name, rate in [("transcript_dji_12x", "cutlist_dji_12x", 1.2),
                               ("transcript_meetily", "cutlist_meetily", 1.0)]:
    transcript = json.loads((root / f"output/{tr_name}.json").read_text())
    cutlist = json.loads((root / f"output/{cl_name}.json").read_text())
    with tempfile.TemporaryDirectory() as td:
        p_cut, p_tr = write_cut_artifacts(
            transcript, segments_from_cutlist(cutlist), "cutlist",
            tr_name.replace("transcript_", ""), rate, Path(td))
        tcut = json.loads(p_tr.read_text())
        assert tcut["origem"] == "cutlist"
        assert tcut["source"]["speed_rate"] == rate
        kept = round(sum(s["end"] - s["start"] for s in cutlist["segments"]), 3)
        assert abs(tcut["cut_duration"] - kept) < 0.01, tr_name
        assert tcut["words"] and all("score" in w for w in tcut["words"])
        assert tcut["offsets"], tr_name
        final = json.loads(p_cut.read_text())
        assert ([s["start"] for s in final["segments"]]
                == [s["start"] for s in cutlist["segments"]])
print("test_cut_artifacts: OK")
```

- [ ] **Step 3.2: Rodar e ver falhar:**

```bash
cd ~/development/EditorClaude && .venv/bin/python tests/test_cut_artifacts.py
```

Expected: `ModuleNotFoundError: No module named 'cut_artifacts'`

- [ ] **Step 3.3: Implementar `src/cut_artifacts.py`:**

```python
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
    words = [w for s in transcript["segments"] for w in s.get("words", [])
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
```

- [ ] **Step 3.4: Rodar e ver passar:**

```bash
.venv/bin/python tests/test_cut_artifacts.py
```

Expected: `test_cut_artifacts: OK`

- [ ] **Step 3.5: Commit**

```bash
git add src/cut_artifacts.py tests/test_cut_artifacts.py
git commit -m "cut_artifacts: persiste o corte do checkpoint 1 (cutlist_final + transcript_cut)"
```

---

### Task 4: `src/format_transcript_md.py` — transcript_cut → prosa MM:SS (TDD)

**Files:**
- Create: `~/development/EditorClaude/src/format_transcript_md.py`
- Test: `~/development/EditorClaude/tests/test_format_transcript.py`

- [ ] **Step 4.1: Teste que falha:**

```python
"""Roda direto: .venv/bin/python tests/test_format_transcript.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from format_transcript_md import mmss, render_md

assert mmss(0.0) == "00:00" and mmss(65.4) == "01:05" and mmss(59.6) == "01:00"

tcut = {"cut_duration": 8.0,
        "offsets": [{"cut_start": 0.0, "cut_end": 5.0},
                    {"cut_start": 5.0, "cut_end": 8.0}],
        "words": [{"word": "Instalei", "clip": 0}, {"word": "o", "clip": 0},
                  {"word": "plugin.", "clip": 0}, {"word": "Funciona", "clip": 1},
                  {"word": "assim.", "clip": 1}]}
md = render_md(tcut, "teste")
lines = md.splitlines()
assert "timestamps REAIS" in lines[0] and "slug: teste" in lines[0]
assert lines[2] == "00:00" and lines[3] == "Instalei o plugin."
assert lines[5] == "00:05" and lines[6] == "Funciona assim."

# segmento sem palavra (ex.: respiro mantido) não vira bloco vazio
tcut2 = {"cut_duration": 3.0,
         "offsets": [{"cut_start": 0.0, "cut_end": 1.0},
                     {"cut_start": 1.0, "cut_end": 3.0}],
         "words": [{"word": "Só", "clip": 1}, {"word": "isso.", "clip": 1}]}
md2 = render_md(tcut2, "x")
assert "00:00\n\n" not in md2 and "00:01" in md2
print("test_format_transcript: OK")
```

- [ ] **Step 4.2: Rodar e ver falhar:**

```bash
.venv/bin/python tests/test_format_transcript.py
```

Expected: `ModuleNotFoundError: No module named 'format_transcript_md'`

- [ ] **Step 4.3: Implementar `src/format_transcript_md.py`:**

```python
"""transcript_cut.json -> transcript_cut_<slug>.md: prosa com marcas MM:SS,
o caminho feliz da skill transcript-to-motion do MotionSkills (mesmo formato
do test-data dela: marca de tempo numa linha isolada + parágrafo de prosa).

A 1ª linha declara "timestamps REAIS do corte" — é o gatilho do modo real no
MotionSkills: brief com duração EXATA de seção, sem margem de +20%.

Uso:
    python src/format_transcript_md.py output/transcript_cut_<slug>.json
"""
import argparse
import json
from pathlib import Path

HEADER = ("Fonte: transcript_cut (timestamps REAIS do corte aprovado) · "
          "slug: {slug} · duração do corte: {dur}s")


def mmss(t: float) -> str:
    m, s = divmod(int(round(t)), 60)
    return f"{m:02d}:{s:02d}"


def render_md(tcut: dict, slug: str) -> str:
    lines = [HEADER.format(slug=slug, dur=tcut["cut_duration"]), ""]
    for i, row in enumerate(tcut["offsets"]):
        block = [w["word"] for w in tcut["words"] if w["clip"] == i]
        if not block:
            continue
        lines.append(mmss(row["cut_start"]))
        lines.append(" ".join(block))
        lines.append("")
    return "\n".join(lines)


def write_transcript_md(tcut: dict, slug: str,
                        out_dir: Path = Path("output")) -> Path:
    p = out_dir / f"transcript_cut_{slug}.md"
    p.write_text(render_md(tcut, slug))
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript_cut", type=Path)
    parser.add_argument("--slug", default=None)
    args = parser.parse_args()
    tcut = json.loads(args.transcript_cut.read_text())
    slug = args.slug or args.transcript_cut.stem.replace("transcript_cut_", "")
    p = write_transcript_md(tcut, slug, out_dir=args.transcript_cut.parent)
    print(f"md: {p}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.4: Rodar e ver passar:**

```bash
.venv/bin/python tests/test_format_transcript.py
```

Expected: `test_format_transcript: OK`

- [ ] **Step 4.5: Commit**

```bash
git add src/format_transcript_md.py tests/test_format_transcript.py
git commit -m "format_transcript_md: transcript_cut -> prosa MM:SS pro MotionSkills"
```

---

### Task 5: `adapters/premiere_mcp/export_cut.py` — comando que fecha o checkpoint 1

**Files:**
- Create: `~/development/EditorClaude/adapters/premiere_mcp/export_cut.py`

Roda quando o usuário terminar a edição manual (Premiere aberto, bridge viva). Lê o corte da timeline e persiste os 3 artefatos. É a ÚNICA parte nova que exige Premiere — tudo a jusante passa a funcionar sem ele.

- [ ] **Step 5.1: Implementar:**

```python
"""Fecha o CHECKPOINT 1: lê o corte FINAL da timeline e persiste os artefatos.

Rodar quando o usuário fechar a edição manual do corte (Premiere aberto, painel
MCP Bridge ativo). Grava cutlist_final_<slug>.json + transcript_cut_<slug>.json
+ transcript_cut_<slug>.md em output/. Depois disso o brief do MotionSkills, o
diff de copy e o re-render ffmpeg funcionam SEM Premiere.

Uso:
    python adapters/premiere_mcp/export_cut.py output/transcript_<slug>.json \
        --sequence-name reel_<slug> [--media-name dji_] [--camera-track 1] \
        [--slug <slug>] [--style seco]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render_premiere import (BRIDGE_TEMP_DIR, SERVER_ENTRY, MCPError,
                             MCPStdioClient, load_style)
from finalize_premiere import read_camera_clips

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from cut_artifacts import (infer_speed_rate, segments_from_clips,
                           write_cut_artifacts)
from format_transcript_md import write_transcript_md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--sequence-name", required=True)
    parser.add_argument("--media-name", default="dji_")
    parser.add_argument("--camera-track", type=int, default=1)
    parser.add_argument("--slug", default=None)
    parser.add_argument("--style", default="seco")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not args.transcript.exists():
        sys.exit(f"não encontrado: {args.transcript}")
    transcript = json.loads(args.transcript.read_text())
    slug = args.slug or args.sequence_name.removeprefix("reel_")

    client = MCPStdioClient(["node", str(SERVER_ENTRY)],
                            env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
                            timeout=args.timeout)
    client.start()
    try:
        seqs = client.call_tool("list_sequences", {})
        seq_id = next((s["id"] for s in seqs.get("sequences", [])
                       if s.get("name") == args.sequence_name), None)
        if not seq_id:
            raise MCPError(f"sequência {args.sequence_name!r} não encontrada")
        client.call_tool("set_active_sequence", {"sequenceId": str(seq_id)})
        clips = read_camera_clips(client, args.camera_track, args.media_name)
    finally:
        client.close()

    rate = infer_speed_rate(
        transcript, load_style(args.style).get("speed", {}).get("rate", 1.2))
    p_cut, p_tr = write_cut_artifacts(transcript, segments_from_clips(clips),
                                      "timeline", slug, rate)
    tcut = json.loads(p_tr.read_text())
    p_md = write_transcript_md(tcut, slug)
    print(f"CHECKPOINT 1 persistido: {len(clips)} clipes, "
          f"corte de {tcut['cut_duration']}s (origem: timeline)")
    print(f"  {p_cut}\n  {p_tr}\n  {p_md}")
    print(f"PRÓXIMO: autorar o brief no MotionSkills a partir de {p_md.name} "
          f"(fala REAL do corte — modo real, sem margem de +20%).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.2: Verificar sem Premiere** (deve falhar com erro de bridge/conexão, nunca de import/argparse):

```bash
.venv/bin/python adapters/premiere_mcp/export_cut.py output/transcript_dji_12x.json --sequence-name reel_teste 2>&1 | tail -3
```

Expected: erro de MCP/conexão/sequência (ex.: timeout do bridge ou `sequência 'reel_teste' não encontrada`) — prova que imports e CLI estão corretos.

- [ ] **Step 5.3: Commit**

```bash
git add adapters/premiere_mcp/export_cut.py
git commit -m "export_cut: fecha o checkpoint 1 persistindo o corte da timeline"
```

---

### Task 6: `prepare_compose` consome transcript_cut + avisa divergência de Dur.

**Files:**
- Modify: `~/development/EditorClaude/src/compose.py` (função `parse_brief_scenes`, ~linha 154)
- Modify: `~/development/EditorClaude/src/prepare_compose.py` (bloco de remap ~linhas 54-64 e loop de print ~linhas 105-108)
- Test: `~/development/EditorClaude/tests/test_compose.py` (adicionar casos no fim, antes do print final — abrir o arquivo e seguir o padrão existente)

- [ ] **Step 6.1: Teste que falha — adicionar ao FIM de `tests/test_compose.py`** (antes da última linha de print, se houver; senão ao final):

```python
# --- parse_brief_scenes lê a coluna Dur. (higiene 2026-08-05) ---
from compose import parse_brief_scenes
brief = """
| # | Trecho (resumo) | Conceito visual | Skill | Dur. | Loop | Layout |
|---|---|---|---|---|---|---|
| 01 | "Instalei o plugin novo" | hook | cinematic-camera | 6s | não | fullscreen |
| 02 | "Funciona assim na prática" | demo | terminal-inserts | 12.5s | sim | split-safe |
"""
scenes = parse_brief_scenes(brief)
assert scenes[0]["dur"] == 6.0 and scenes[1]["dur"] == 12.5
assert scenes[1]["loop"] is True
print("parse_brief_scenes lê Dur.: OK")
```

- [ ] **Step 6.2: Rodar e ver falhar:**

```bash
.venv/bin/python tests/test_compose.py
```

Expected: `KeyError: 'dur'` (os asserts antigos continuam passando).

- [ ] **Step 6.3: Implementar em `parse_brief_scenes`** — trocar o `scenes.append(...)` por:

```python
        trecho = cells[1].strip().strip('"').lstrip("…").strip()
        m_dur = re.search(r"([\d]+(?:[.,]\d+)?)\s*s", cells[4]) if len(cells) > 4 else None
        scenes.append({"num": cells[0],
                       "match": " ".join(trecho.split()[:5]),
                       "dur": float(m_dur.group(1).replace(",", ".")) if m_dur else None,
                       "loop": cells[5].strip().lower().startswith("s")})
```

- [ ] **Step 6.4: Rodar e ver passar:**

```bash
.venv/bin/python tests/test_compose.py
```

Expected: termina com `parse_brief_scenes lê Dur.: OK` e todos os OKs anteriores.

- [ ] **Step 6.5: `prepare_compose.py` — aceitar transcript_cut** — trocar o bloco atual (`slug = args.cutlist.stem...` até o `sys.exit` do remap vazio) por:

```python
    transcript = json.loads(args.transcript.read_text())
    cutlist = json.loads(args.cutlist.read_text())
    if "offsets" in transcript:
        # transcript_cut_<slug>.json: palavras JÁ em tempo de corte (fluxo do
        # checkpoint — chamar com output/cutlist_final_<slug>.json como cutlist)
        out_words = transcript["words"]
        slug = args.transcript.stem.replace("transcript_cut_", "")
        print(f"modo corte-aprovado: {len(out_words)} palavras do "
              f"transcript_cut (origem: {transcript.get('origem')})")
    else:
        words = [w for s in transcript["segments"] for w in s.get("words", [])
                 if "start" in w]
        out_words = remap_words(words, cutlist["segments"])
        slug = args.cutlist.stem.replace("cutlist_", "")
    if not out_words:
        sys.exit("nenhuma palavra sobreviveu ao remap — cutlist/transcript batem?")
    out_manifest = args.out_manifest or Path(f"output/motion_manifest_{slug}.json")
    out_srt = args.out_srt or Path(f"output/captions_{slug}.srt")
```

ATENÇÃO: no arquivo atual, as linhas `slug = ...`, `out_manifest = ...` e `out_srt = ...` vêm ANTES da leitura dos JSONs — esta mudança move a definição de slug/paths para DEPOIS (o slug agora depende do modo). Conferir que nenhuma variável é usada antes de definida.

- [ ] **Step 6.6: `prepare_compose.py` — aviso de Dur. divergente** — no loop de print final, trocar:

```python
    for i, sc in enumerate(scenes):
        end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        secao = end - sc["start"]
        print(f"  {Path(sc['clip']).name:20s} t={sc['start']:6.2f}s "
              f"secao={secao:5.2f}s loop={sc['loop']}")
        if sc.get("dur") and abs(secao - sc["dur"]) > 0.5:
            print(f"    AVISO: brief declara {sc['dur']}s, seção real tem "
                  f"{secao:.2f}s — motion será truncado ou vai sobrar "
                  f"(brief autorado sobre fala errada? use o transcript_cut)")
```

- [ ] **Step 6.7: Teste de regressão do caminho antigo com dados reais** (o meetily tem brief? Se `~/development/MotionSkills/motion-graphics/src/videos/` não tiver dir com brief + clips renderizados, pular execução e validar só por leitura de código):

```bash
ls ~/development/MotionSkills/motion-graphics/src/videos/
```

Se existir `<nome>` com `brief.md` E `~/development/MotionSkills/motion-graphics/out/<nome>/clips/*.mp4`:

```bash
.venv/bin/python src/prepare_compose.py output/transcript_meetily.json output/cutlist_meetily.json ~/development/MotionSkills/motion-graphics/src/videos/<nome> --out-manifest /tmp/m.json --out-srt /tmp/c.srt
```

Expected: roda até o fim como antes (manifest + srt gerados), agora possivelmente com AVISOs de Dur.

- [ ] **Step 6.8: Commit**

```bash
git add src/compose.py src/prepare_compose.py tests/test_compose.py
git commit -m "prepare_compose: modo transcript_cut (fala real) + aviso de Dur. divergente no brief"
```

---

### Task 7: `finalize_premiere` refresca artefatos + avisa seção > motion

**Files:**
- Modify: `~/development/EditorClaude/adapters/premiere_mcp/finalize_premiere.py` (imports ~linha 43, após `out_words = remap_words_by_clips(...)` ~linha 180, e após `starts = find_scene_starts(...)` ~linha 187)

- [ ] **Step 7.1: Imports novos** — junto ao bloco `sys.path.insert(...)/src` existente:

```python
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from compose import (find_scene_starts, format_srt, group_captions,
                     merge_corrected_text, parse_srt, remap_words_by_clips)
from cut_artifacts import (infer_speed_rate, segments_from_clips,
                           write_cut_artifacts)
from format_transcript_md import write_transcript_md


def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())
```

- [ ] **Step 7.2: Refresh dos artefatos** — logo após o bloco `out_words = remap_words_by_clips(words, clips)` / `if not out_words: raise ...`:

```python
        # o corte ATUAL da timeline vira artefato — mantém transcript_cut fresco
        # a cada etapa (o usuário pode ter retocado o corte entre etapas)
        slug = args.sequence_name.removeprefix("reel_")
        rate = infer_speed_rate(
            transcript, style.get("speed", {}).get("rate", 1.2))
        p_cut, p_tr = write_cut_artifacts(
            transcript, segments_from_clips(clips), "timeline", slug, rate)
        write_transcript_md(json.loads(p_tr.read_text()), slug)
        print(f"artefatos do corte atualizados: {p_cut.name}, {p_tr.name}")
```

- [ ] **Step 7.3: Aviso seção > motion** — logo após o `for sc, st in zip(scenes, starts): sc["start"] = st`:

```python
            for i, sc in enumerate(scenes):
                span = ((scenes[i + 1]["start"] if i + 1 < len(scenes)
                         else total) - sc["start"])
                dur = media_duration(Path(sc["clip"]))
                if span > dur + 0.05:
                    modo = ("marcado como loop, mas o caminho Premiere NÃO "
                            "faz loop — repetir o clipe à mão"
                            if sc.get("loop") else "sem loop")
                    print(f"    AVISO: seção de {span:.2f}s > motion de "
                          f"{dur:.2f}s ({Path(sc['clip']).name}, {modo})")
```

- [ ] **Step 7.4: Rodar teste existente do finalize (se houver) e smoke de import:**

```bash
.venv/bin/python -c "import sys; sys.path.insert(0, 'adapters/premiere_mcp'); sys.path.insert(0, 'adapters'); import finalize_premiere; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 7.5: Commit**

```bash
git add adapters/premiere_mcp/finalize_premiere.py
git commit -m "finalize: refresca artefatos do corte a cada etapa + avisa seção maior que o motion"
```

---

### Task 8: `src/diff_copy.py` — trava do checkpoint 2 (TDD)

**Files:**
- Create: `~/development/EditorClaude/src/diff_copy.py`
- Test: `~/development/EditorClaude/tests/test_diff_copy.py`

**FRONTEIRA (requisito da spec):** este script NUNCA escreve no vault e NUNCA lê métrica. Relatório em `output/`; a conclusão qualitativa quem leva pro vault é o operador (Task 10).

- [ ] **Step 8.1: Teste que falha:**

```python
"""Roda direto: .venv/bin/python tests/test_diff_copy.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from diff_copy import diff_chunks, render_report, strip_markdown, tokenize

copy = "te mando o passo a passo e o convite pro meu grupo"
falado = "te mando o passo a passo e me segue pra não perder"
chunks = diff_chunks(tokenize(copy), tokenize(falado))
assert len(chunks) == 1 and chunks[0]["tipo"] == "replace"
assert "convite" in chunks[0]["copy"] and "segue" in chunks[0]["falado"]
assert chunks[0]["contexto"].endswith("passo e")

md = "---\ntipo: copy\n---\n# Título\nfala **real** aqui\n<!-- nota -->"
assert tokenize(strip_markdown(md)) == ["fala", "real", "aqui"]

tcut = {"cut_duration": 30.0, "source": {"speed_rate": 1.2}, "words": []}
report = render_report(chunks, tokenize(copy), tcut, "teste")
assert "36.0s" in report                      # 30.0 × 1.2 = ritmo natural
assert "12 palavras" in report                # a copy do teste
assert "sinal de ritmo" not in report         # 36s natural > ~4.8s da copy:
                                              # alerta só quando falou RÁPIDO
# caso "falou rápido": copy longa (60 tokens ~24s) e fala natural de 12s
copy_longa = ["palavra"] * 60
tcut_rapido = {"cut_duration": 10.0, "source": {"speed_rate": 1.2}, "words": []}
report2 = render_report([], copy_longa, tcut_rapido, "x")
assert "sinal de ritmo" in report2
print("test_diff_copy: OK")
```

- [ ] **Step 8.2: Rodar e ver falhar:**

```bash
.venv/bin/python tests/test_diff_copy.py
```

Expected: `ModuleNotFoundError: No module named 'diff_copy'`

- [ ] **Step 8.3: Implementar `src/diff_copy.py`:**

```python
"""Diff copy aprovada × fala real do corte — TRAVA do checkpoint 2 (pré-publicação).

Compara o texto da copy (arquivo .md/.txt exportado do EstudoConteudo — é lá
que a copy aprovada mora) com as palavras do transcript_cut.json. Reporta as
divergências com contexto + durações (publicada e em ritmo natural, usando
source.speed_rate — sem essa correção todo vídeo 1.2x pareceria "falado
rápido"). O operador julga CTA, fosso e keyword ANTES de publicar.

FRONTEIRA: nunca escreve no vault, nunca lê métrica. Relatório em
output/diff_copy_<slug>.md; a conclusão qualitativa vai pro vault pela mão do
operador (seção datada em 'O vídeo gravado não é o roteiro aprovado').

Uso:
    python src/diff_copy.py <copy.md> output/transcript_cut_<slug>.json
"""
import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose import normalize_text


def tokenize(text: str) -> list[str]:
    return normalize_text(text).split()


def strip_markdown(text: str) -> str:
    """Remove frontmatter, comentários, cabeçalhos e ênfases — sobra a fala."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s.*$", " ", text, flags=re.M)
    return re.sub(r"[*_`>|]", " ", text)


def diff_chunks(copy_tokens: list[str], spoken_tokens: list[str],
                context: int = 4) -> list[dict]:
    matcher = SequenceMatcher(None, copy_tokens, spoken_tokens, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        out.append({"tipo": tag,
                    "copy": " ".join(copy_tokens[i1:i2]),
                    "falado": " ".join(spoken_tokens[j1:j2]),
                    "contexto": " ".join(copy_tokens[max(0, i1 - context):i1])})
    return out


def render_report(chunks: list[dict], copy_tokens: list[str],
                  tcut: dict, slug: str) -> str:
    rate = tcut["source"].get("speed_rate", 1.0)
    cut_dur = tcut["cut_duration"]
    natural = round(cut_dur * rate, 1)
    copy_est = round(len(copy_tokens) / 2.5, 1)  # 150 palavras/min PT-BR
    lines = [f"# Diff copy × fala — {slug}", "",
             f"- duração publicada (corte): {cut_dur}s",
             f"- fala em ritmo natural (×{rate}): {natural}s",
             f"- copy: {len(copy_tokens)} palavras (~{copy_est}s a 150 ppm)", ""]
    if copy_est and natural < copy_est * 0.85:
        lines += ["⚠️ fala natural bem mais curta que a copy — sinal de ritmo "
                  "acelerado na gravação (ritmo é retenção; ver 'O vídeo "
                  "gravado não é o roteiro aprovado')", ""]
    if not chunks:
        lines.append("Nenhuma divergência de texto entre copy e fala. ✅")
    else:
        lines += [f"## {len(chunks)} divergências — revisar CTA, fosso e keyword", "",
                  "| contexto (copy) | na copy | falado |", "|---|---|---|"]
        for c in chunks:
            lines.append(f"| …{c['contexto']} | {c['copy'] or '—'} "
                         f"| {c['falado'] or '—'} |")
    lines += ["", "TRAVA: divergência em CTA ou fosso = corrigir ANTES de "
              "publicar (regravar trecho ou aceitar por escrito).",
              "Pós-publicação: conclusão qualitativa vira seção datada na nota "
              "'O vídeo gravado não é o roteiro aprovado' do vault. "
              "Métrica NUNCA vai pro vault."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("copy", type=Path,
                        help="arquivo .md/.txt da copy aprovada (EstudoConteudo)")
    parser.add_argument("transcript_cut", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()
    for p in (args.copy, args.transcript_cut):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    tcut = json.loads(args.transcript_cut.read_text())
    slug = args.transcript_cut.stem.replace("transcript_cut_", "")
    copy_tokens = tokenize(strip_markdown(args.copy.read_text()))
    spoken_tokens = tokenize(" ".join(w["word"] for w in tcut["words"]))
    chunks = diff_chunks(copy_tokens, spoken_tokens)
    report = render_report(chunks, copy_tokens, tcut, slug)
    out = args.out or Path(f"output/diff_copy_{slug}.md")
    out.write_text(report)
    print(report)
    print(f"\nrelatório: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Rodar e ver passar:**

```bash
.venv/bin/python tests/test_diff_copy.py
```

Expected: `test_diff_copy: OK`

- [ ] **Step 8.5: Commit**

```bash
git add src/diff_copy.py tests/test_diff_copy.py
git commit -m "diff_copy: trava do checkpoint 2 — copy aprovada × fala real do corte"
```

---

### Task 9: MotionSkills — modo real (durações exatas) + entrada por arquivo

**Files:**
- Modify: `~/development/MotionSkills/motion-graphics/.claude/skills/transcript-to-motion/SKILL.md` (§1 e §4)
- Modify: `~/development/MotionSkills/motion-graphics/CLAUDE.md` (GOLDEN RULE, item da linha ~19)
- Create: `~/development/MotionSkills/CLAUDE.md` (raiz do repo — ponteiro)

- [ ] **Step 9.1: SKILL.md §1 (Input detection)** — adicionar como PRIMEIRO bullet da lista:

```markdown
- A file path or pasted content whose FIRST line contains `timestamps REAIS do corte` → **real-mode**: this is the transcript of the APPROVED CUT (`transcript_cut_<slug>.md`, written by EditorClaude's checkpoint). If given a path, Read the file. Real-mode changes §4 — durations are exact, not estimated.
```

- [ ] **Step 9.2: SKILL.md §4 (Duration & safety margin)** — adicionar ao FIM da seção:

```markdown
- **Real-mode (transcript of the approved cut):** scene duration = EXACT speech time of its excerpt — no +20%, no 3s minimum. Master duration = the cut duration declared in the header line — no ×1.2, no rounding up. The +20% / min-3s / ×1.2 rules exist to absorb ESTIMATION error; with checkpoint timestamps there is none, and any padding becomes truncated frames downstream (`build_mg_clips` trims, never stretches). Loopable scenes are still marked (loop is texture, not time-filling, in real-mode).
```

- [ ] **Step 9.3: GOLDEN RULE no CLAUDE.md** — trocar o item 2 da regra (que hoje diz para invocar a skill quando o usuário cola transcrição) para cobrir caminho de arquivo. Localizar a linha da GOLDEN RULE que descreve o gatilho e acrescentar após ela:

```markdown
The same rule applies when the user provides a PATH to a `transcript_cut_*.md` file (EditorClaude checkpoint output): Read it and run the full pipeline in real-mode (see the transcript-to-motion skill, §1/§4 — exact durations, no +20%).
```

- [ ] **Step 9.4: Criar `~/development/MotionSkills/CLAUDE.md`** (raiz — o projeto real vive em `motion-graphics/`):

```markdown
# MotionSkills

O projeto real vive em `motion-graphics/` — leia `motion-graphics/CLAUDE.md`
(regras de pipeline, GOLDEN RULE, convenções de render).

Papel no pipeline do canal: recebe do EditorClaude o `transcript_cut_<slug>.md`
(fala REAL do corte aprovado no checkpoint 1) e autora o brief em modo real —
durações exatas por seção, sem margem de +20%. Nunca autorar brief sobre a copy
pré-gravação quando existir transcript_cut do vídeo.
```

- [ ] **Step 9.5: Verificar e commitar (MotionSkills):**

```bash
cd ~/development/MotionSkills/motion-graphics
grep -n "real-mode" .claude/skills/transcript-to-motion/SKILL.md CLAUDE.md
git add .claude/skills/transcript-to-motion/SKILL.md CLAUDE.md ../CLAUDE.md
git commit -m "transcript-to-motion: modo real (transcript_cut do EditorClaude, durações exatas)"
```

Expected do grep: ≥3 ocorrências (2 no SKILL.md, 1 no CLAUDE.md).

---

### Task 10: EditorClaude — SKILL.md v2 do fluxo, CLAUDE.md e README

**Files:**
- Modify: `~/development/EditorClaude/.claude/skills/rough-cut/SKILL.md` (seção 3b, ~linhas 94-141)
- Create: `~/development/EditorClaude/CLAUDE.md`
- Modify: `~/development/EditorClaude/README.md` (linhas 117-118 e ~230)

- [ ] **Step 10.1: SKILL.md — substituir o bloco de comandos da seção 3b** (do `# 1. cola: manifest resolvido...` até o fim do bloco ```bash com o qa_captions) por:

```bash
# 1. ETAPA CORTE: timeline só com câmera + voz (V1 vazia -> Close Gap
#    funciona; SEM manifest — o brief nasce DEPOIS do corte)
.venv/bin/python adapters/premiere_mcp/compose_premiere.py <video> output/cutlist_<slug>.json --sequence-name reel_<slug> --somente-corte
# 2. CHECKPOINT 1: usuário edita o corte e avisa quando fechou. Ao fechar,
#    PERSISTIR o corte (única etapa que exige Premiere aberto):
.venv/bin/python adapters/premiere_mcp/export_cut.py output/transcript_<slug>.json --sequence-name reel_<slug>
# 3. BRIEF NO MOTIONSKILLS a partir da fala REAL do corte: abrir sessão no
#    MotionSkills passando output/transcript_cut_<slug>.md (modo real da skill
#    transcript-to-motion — durações exatas, sem +20%). Renderizar os clips.
# 4. cola: manifest resolvido + SRT MAIÚSCULO — usar os ARTEFATOS DO CORTE
#    (não o transcript/cutlist originais, que ficaram pra trás no checkpoint):
.venv/bin/python src/prepare_compose.py output/transcript_cut_<slug>.json output/cutlist_final_<slug>.json ~/development/MotionSkills/motion-graphics/src/videos/<nome>
# 5. REVISAR o SRT contra o brief (transcrição erra: cloud->Claude,
#    admira->ADMIN...) — corrigir SÓ texto, nunca timestamps
# 6. ETAPA MOTIONS: lê o corte ATUAL da timeline, sobe motions fatiados nos
#    cortes reais + música + punch-in, e REFRESCA os artefatos do corte:
.venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa motions
# 7. CHECKPOINT 2: usuário revisa dinamismo; COR manual (Paste Attributes da
#    referência em V2, NUNCA Motion/Crop). ANTES DE PUBLICAR, a TRAVA:
.venv/bin/python src/diff_copy.py <copy-aprovada.md> output/transcript_cut_<slug>.json
#    Divergência em CTA ou fosso = corrigir antes de publicar. A copy aprovada
#    vem do EstudoConteudo (tabela copies / arquivo de copy do repo).
# 8. ETAPA LEGENDAS (sempre a última — lê o áudio ATUAL da timeline):
.venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa legendas --corrected-srt output/captions_<slug>.srt
# 9. QA DA LEGENDA (sempre rodar após a etapa legendas): re-transcreve o áudio
#    do corte final e diffa com a legenda — pega frase que o ASR ENGOLIU.
.venv/bin/python adapters/premiere_mcp/qa_captions_premiere.py <video> output/captions_reel_<slug>_final.srt --sequence-name reel_<slug>
# 10. PÓS-PUBLICAÇÃO (destilação pro vault): a conclusão do diff (passo 7)
#    vira seção datada apendada em
#    "~/development/2Cerebro/03 Recursos/Aprendizados de Conteúdo/O vídeo
#    gravado não é o roteiro aprovado.md" (conclusão qualitativa em português;
#    MÉTRICA NUNCA) + 1 linha no topo de
#    "~/development/2Cerebro/99 Contexto/log.md".
```

Manter intactos os parágrafos após o bloco (motion como autorado, música, cor, Track Style) e o restante da skill.

- [ ] **Step 10.2: Criar `~/development/EditorClaude/CLAUDE.md`:**

```markdown
# EditorClaude — operador

Pipeline de edição do canal operado por Claude Code. A receita completa está na
skill `.claude/skills/rough-cut/` — invocá-la sempre que o pedido for editar,
cortar ou compor vídeo. Setup, comandos manuais e formatos: `README.md`.

## Papel no pipeline do canal (fluxo com checkpoints)

Este repo é o dono da FONTE DE VERDADE DO CORTE. No fechamento do CHECKPOINT 1
(usuário aprova o corte na timeline), `export_cut.py` persiste:

- `output/cutlist_final_<slug>.json` — o corte real, re-renderizável sem Premiere
- `output/transcript_cut_<slug>.json` — fala remapeada pro tempo do corte
  (score, silences, offsets corte↔fonte, `source.speed_rate`)
- `output/transcript_cut_<slug>.md` — prosa MM:SS que o MotionSkills consome
  em modo real (brief com durações EXATAS)

O brief de motion NUNCA nasce da copy pré-gravação quando existe transcript_cut.
No CHECKPOINT 2, `diff_copy.py` compara copy aprovada × fala real — trava de
publicação (CTA, fosso, keyword). Timestamps de fonte referem-se ao arquivo
transcrito (na prática o `_12x`; o fator vive em `source.speed_rate`).

## Contexto canônico

Decisão criativa/de negócio → ler o vault (herdado do CLAUDE.md de
`~/development`): `~/development/2Cerebro/99 Contexto/`.
```

- [ ] **Step 10.3: README — corrigir as duas linhas desatualizadas.** Read no `README.md`; na linha ~117-118 (diagrama do pipeline), trocar:

```
  adapters/premiere_mcp/ (esqueleto)
  timeline no Premiere (bloqueado)
```

por:

```
  adapters/premiere_mcp/ (funcional)
  timeline no Premiere (E2E validado 2026-07-30)
```

Na linha ~230 (descrição do diretório), trocar o trecho `esqueleto do adaptador Premiere Pro MCP (não instalado)` por `adaptador Premiere Pro MCP — FUNCIONAL, E2E validado 2026-07-30 (setup: adapters/premiere_mcp/README.md)`. Conferir o texto exato com Read antes de editar (a redação pode variar levemente).

- [ ] **Step 10.4: Rodar TODOS os testes do repo:**

```bash
cd ~/development/EditorClaude
for t in tests/test_*.py; do echo "== $t"; .venv/bin/python "$t" || break; done
```

Expected: todos imprimem OK (test_compose_premiere e afins não dependem de Premiere).

- [ ] **Step 10.5: Commit**

```bash
git add .claude/skills/rough-cut/SKILL.md CLAUDE.md README.md
git commit -m "Fluxo v2 com checkpoint persistido: brief nasce do corte; diff de copy como trava; docs atualizados"
```

---

### Task 11: Vault — registrar a execução

**Files:**
- Modify: `~/development/2Cerebro/99 Contexto/log.md` (append no TOPO, abaixo do título)
- Modify: `~/development/2Cerebro/01 Projetos/Internos/Fundação 2Cerebro e pipeline de vídeo.md` (checkboxes)

Caminhos têm espaço — sempre entre aspas. NUNCA editar nada além do append no log e da página de projeto.

- [ ] **Step 11.1: Entrada no log** (ajustar a data para o dia real da execução):

```markdown
## [YYYY-MM-DD] execução | Fundação (guarda-chuva) + pipeline com checkpoint implementados
CLAUDE.md guarda-chuva criado em ~/development (contrato de duas vias + exceções
Addept/SalesDever). EditorClaude: export_cut persiste o checkpoint 1
(cutlist_final + transcript_cut + .md prosa MM:SS), prepare_compose consome a
fala real, finalize refresca artefatos e avisa seção>motion, diff_copy é a trava
do checkpoint 2. MotionSkills: modo real na transcript-to-motion (durações
exatas, sem +20%). Higiene: README corrigido (Premiere funcional), coluna Dur.
do brief agora validada. Pendente: validação E2E no próximo vídeo real.
```

- [ ] **Step 11.2: Página de projeto** — marcar `- [x]` nas ações executadas (plano escrito, Parte 1, Parte 2) e adicionar:

```markdown
- [ ] Validar E2E no próximo vídeo real do canal (Task 12 do plano)
```

---

### Task 12: Validação E2E (manual, com o Luiz, no próximo vídeo real)

**Files:** nenhum — checklist de aceite (critérios de sucesso da spec)

- [ ] **12.1:** Gravar um vídeo novo e rodar o fluxo v2 completo (SKILL 3b): corte → checkpoint 1 → `export_cut` → brief no MotionSkills via `transcript_cut_<slug>.md` → render → `prepare_compose` com os artefatos do corte → motions → checkpoint 2 com `diff_copy` → legendas → QA.
- [ ] **12.2 (critério 2):** conferir no relatório do prepare_compose que NENHUMA cena tem AVISO de divergência >0.5s, e no vídeo final que nenhum motion foi truncado no meio de um beat.
- [ ] **12.3 (critério 3):** fechar o Premiere depois do checkpoint 1 e confirmar que brief + diff_copy rodam só com os artefatos.
- [ ] **12.4 (critério 4):** o diff rodou ANTES de publicar; pós-publicação, a seção datada entrou na nota do vault e o log registrou.
- [ ] **12.5 (critério 1):** abrir sessão de Claude Code em 2 repos sem CLAUDE.md próprio (ex.: Nexor, CV'sFormaly) e confirmar que o contrato do guarda-chuva responde.
- [ ] **12.6:** Merge dos branches (`fundacao-pipeline-checkpoint` no EditorClaude, `transcript-cut-real-mode` no MotionSkills) — usar a skill superpowers:finishing-a-development-branch.

---

## Fora do plano (pendências do Luiz — spec, seção "Pendências")

1. Registrar decisão em `99 Contexto/decisoes/` (híbrido, ordem dos subprojetos, EditorClaude no ecossistema, nome "Destilação pro vault").
2. Atualizar tabela "Ecossistema técnico" de `contexto-luiz.md` (adicionar EditorClaude).
3. Corrigir wording de imutabilidade dos repos no CLAUDE.md do vault.

## Notas para o executor

- `output/` do EditorClaude é gitignored: `cutlist_final_*`, `transcript_cut_*` e `diff_copy_*` NÃO são commitados (como os demais artefatos).
- Os testes com dados reais dependem de `output/transcript_dji_12x.json` e `output/cutlist_dji_12x.json` (existem hoje). Se sumirem, regenerar com os passos 1-2 da skill rough-cut sobre o footage dji.
- O corte do `plugin-administrativo` NÃO existe em `output/` — por isso os testes usam dji/meetily (achado 2 da revisão da Peneira).
- PostCarrossel (reativação + apagar `src/positioning.ts`) pertence ao subprojeto 5 (Conteúdo) — fora deste plano de propósito.
```