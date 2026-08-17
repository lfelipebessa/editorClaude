# EditorClaude

Pipeline de edição do canal, operado por Claude Code. Scripts Python fazem o
trabalho pesado (transcrever, decidir cortes, enquadrar, renderizar) e o Claude
Code atua como operador: você abre o Claude Code na pasta e pede o que quer.

O repositório ensina o operador a trabalhar:

- `.claude/skills/rough-cut/` — a receita que o Claude Code segue, com as regras
  duras e o que nunca fazer. **É o documento mais importante do repo.**
- `styles/seco.json` — o gosto do canal (agressividade do corte, loudness, cor,
  música, legenda). Fonte única de verdade: mudou o gosto, muda aqui, nunca no
  código.
- `.mcp.json` — acesso direto ao Premiere Pro (opcional, ~280 ferramentas MCP).

## Os dois pipelines

O repo faz **duas coisas diferentes**. Saber em qual você está resolve 90% da
confusão:

| | **A — Reel do canal** | **B — Cortes de YouTube** |
|---|---|---|
| Entrada | vídeo bruto de câmera (DJI/celular) | vídeo longo já gravado (tela + webcam) |
| Saída | 1 Reel com motion graphics, legendas e cor | N cortes verticais tela em cima, rosto embaixo |
| Ferramenta | Premiere (timeline) ou ffmpeg (mp4) | ffmpeg direto |
| Checkpoints | 2 (corte, depois dinamismo+cor) | 1 (folha de contato antes do render) |
| Quando usar | vídeo gravado para virar Reel | reaproveitar um vídeo do YouTube nas redes |

Os dois compartilham o transcritor, o style e o núcleo (`core/`).

## Instalação

```bash
git clone https://github.com/lfelipebessa/editorClaude.git
cd editorClaude

python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt   # WhisperX puxa PyTorch: demora
.venv/bin/pip install -e .                  # torna `core` importável

.venv/bin/python -m pytest tests/ -q        # 101 testes, ~3s, sem vídeo
```

O `pip install -e .` é o que faz `from core import ...` funcionar de qualquer
script — sem ele os adaptadores não encontram a biblioteca compartilhada.

Na **primeira transcrição** o WhisperX baixa ~2–3 GB de modelos, uma vez só.

Requisitos: macOS + Homebrew, `ffmpeg` em `/opt/homebrew/bin/ffmpeg`,
Python 3.11+. Opcionais: Node 18+ e Premiere Pro (só para o pipeline A em
timeline).

### Usando com o Claude Code

```bash
cd editorClaude && claude
```

Depois é conversa: *"edita esse vídeo: ~/Downloads/bruto.mp4"* ou *"gera 3
cortes desse vídeo do YouTube"*. A skill assume e executa. Para mudar estilo de
forma permanente, peça para ele editar `styles/seco.json`.

---

## Pipeline A — Reel do canal

```
bruto ─▶ speedup 1.2x ─▶ transcribe ─▶ cutlist ─┬─▶ render_ffmpeg  → mp4
                                                └─▶ compose_premiere → timeline
                                                        │
                            handoff → MotionSkills ─────┤
                                                        ▼
                                          finalize_premiere (motion, música,
                                          punch-in, legendas) → Reel
```

```bash
.venv/bin/python src/speedup.py bruto.mp4                      # 1.2x, pitch preservado
.venv/bin/python src/transcribe.py bruto_12x.mp4 -o output/transcript_<slug>.json --language pt
.venv/bin/python src/cutlist.py output/transcript_<slug>.json --preset seco -o output/cutlist_<slug>.json
.venv/bin/python adapters/render_ffmpeg.py bruto_12x.mp4 output/cutlist_<slug>.json -o ~/Downloads/rough_cut.mp4
```

Passos de composição (timeline, handoff de motion, legendas, trava de copy):
o fluxo completo com checkpoints está na skill `rough-cut`, seção 3b.

| Script | O que faz |
|---|---|
| `src/speedup.py` | acelera 1.2x antes de tudo (Instagram pede fala veloz) |
| `src/transcribe.py` | vídeo → transcript com timestamps por palavra + silêncios |
| `src/cutlist.py` | transcript → cut-list (silêncio, gaguejo, falso começo, retake) |
| `src/prepare_compose.py` | resolve o manifest de motion + SRT do corte |
| `src/prepare_motion_handoff.py` | corte aprovado → briefing para o MotionSkills |
| `src/diff_copy.py` | trava de publicação: copy aprovada × fala real |
| `src/cut_artifacts.py` | persiste o corte aprovado (re-renderizável sem Premiere) |
| `adapters/render_ffmpeg.py` | cut-list → mp4 |
| `adapters/compose_ffmpeg.py` | bruto + cut-list + motion → Reel 1080×1920 em um encode |
| `adapters/premiere_mcp/` | mesma coisa em timeline editável (setup: README de lá) |

## Pipeline B — Cortes de YouTube

```
gravação Screen Studio ─▶ transcribe ─▶ propose_cuts ─▶ build_recipes ─▶ reel_screencam
   (bundle .screenstudio)                (escolhe os      (encosta na      (tela em cima,
                                          trechos)         palavra)         rosto embaixo)
```

```bash
# offsets das sessões do bundle dentro do export (medidos, nunca chutados)
.venv/bin/python src/sync_screenstudio.py <bundle>.screenstudio <export>.mp4 -o output/sync_<slug>.json

.venv/bin/python src/transcribe.py <export>.mp4 -o output/transcript_<slug>.json --language pt

# briefing de escolha dos trechos -> o AGENTE da sessão responde (não chama API)
.venv/bin/python src/propose_cuts.py output/transcript_<slug>.json -n 3

# propostas -> receitas, com avisos de sobreposição/repetição/duração
.venv/bin/python src/build_recipes.py output/propostas_<slug>.json \
    output/transcript_<slug>.json --base output/reel_<algum>_<slug>.json --slug <slug>

# CONFERIR o enquadramento antes de gastar render
.venv/bin/python adapters/reel_screencam.py output/reel_<tema>_<slug>.json --contact-sheet /tmp/folha.jpg
.venv/bin/python adapters/reel_screencam.py output/reel_<tema>_<slug>.json -o ~/Downloads/reel_<tema>.mp4
```

Estrutura selada do corte: **gancho (o ponto alto puxado do FIM) → problema →
passos → execução → payoff → CTA**. Detalhes e as armadilhas do bundle (sessões,
bolha da webcam, VFR) na skill `rough-cut`, seção 3d.

---

## O núcleo (`core/`)

Biblioteca compartilhada pelos dois pipelines. Antes morava dentro de
`adapters/render_ffmpeg.py`, que é um CLI — por isso 25 arquivos carregavam
`sys.path.insert` só para importá-la. Hoje é um pacote de verdade.

| Módulo | Responsabilidade |
|---|---|
| `core.style` | lê `styles/*.json`, plataformas de saída, biblioteca de música |
| `core.filters` | monta as cadeias de filtro (cor, áudio, música, acabamento, corte) — só string, não executa |
| `core.media` | conversa com ffmpeg/ffprobe: sonda streams, mede loudness |
| `core.transcript` | palavras, remapeamento para o tempo do corte, legendas, SRT |

A separação entre `filters` (monta) e `media` (executa) é o que permite testar
as cadeias sem tocar em vídeo nenhum.

## Contrato: a cut-list (pipeline A)

Todo adaptador de saída consome exatamente este formato e nada mais — nenhum
adaptador lê o transcript diretamente.

```json
{
  "version": 1,
  "source": { "path": "/caminho/absoluto/video.mp4", "duration": 132.48 },
  "segments": [
    { "start": 1.84, "end": 7.02, "text": "fala do segmento", "reason": "speech" }
  ],
  "removed": [
    { "start": 0.0, "end": 1.84, "reason": "silence", "text": "" }
  ],
  "stats": { "kept_duration": 98.7, "removed_duration": 33.78, "segment_count": 12 }
}
```

- `version` — incrementa em toda mudança incompatível.
- `segments` — trechos a MANTER, em ordem, não sobrepostos, já com o respiro
  incluído. O adaptador não adiciona margem.
- `removed` — auditoria. `reason` ∈ `silence` | `stutter` | `false_start` |
  `repetition` | `filler`. Adaptadores ignoram.
- `settings` e `stats` — informativos, ignorar.

Um adaptador correto concatena os `segments` cortando `[start, end)` do original.
Nada além disso.

O transcript traz também `silences` (spans detectados por `silencedetect`): o
aligner do WhisperX às vezes estica uma palavra por cima de uma pausa longa e o
silêncio some dos timestamps, então o `cutlist.py` usa os silêncios como cortes
obrigatórios, independentes do texto.

## Estrutura

```
core/           biblioteca compartilhada (style, filtros, mídia, transcript)
src/            passos de linha de comando dos dois pipelines
adapters/       saídas: render_ffmpeg, compose_ffmpeg, reel_screencam
  premiere_mcp/   saída em timeline do Premiere (setup no README de lá)
styles/         o gosto do canal — seco.json é o padrão
assets/         músicas e LUTs
tests/          101 testes; rodam sem vídeo, exceto os que usam make_fixture.sh
docs/           specs e planos das decisões grandes
vendor/         MCP do Premiere (gitignored, clonar à parte)
output/         artefatos de trabalho (gitignored)
```

## Testes

```bash
.venv/bin/python -m pytest tests/ -q          # tudo
.venv/bin/python tests/test_cutlist.py        # ou cada arquivo direto
tests/make_fixture.sh                         # gera o vídeo usado por alguns testes
```

**Regra ao escrever teste:** valor que vive em `styles/*.json` é calibragem e
muda — o teste lê do style e checa a faixa ou o invariante. Valor que é
constante de código (ex.: o enquadramento selado da câmera) é decisão travada —
o teste fixa o número de propósito, para que mudá-lo seja explícito. Teste que
fixa valor de style quebra a cada calibragem e acaba ignorado.

## Setup opcional: Premiere Pro via MCP

O servidor MCP não vem no clone (gitignored):

```bash
git clone https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP vendor/Adobe_Premiere_Pro_MCP
cd vendor/Adobe_Premiere_Pro_MCP && npm install && npm run build
```

Ajuste o caminho absoluto em `.mcp.json` e siga o setup dentro do Premiere
(extensão CEP + painel MCP Bridge): passo a passo e fragilidades conhecidas em
[`adapters/premiere_mcp/README.md`](adapters/premiere_mcp/README.md).
