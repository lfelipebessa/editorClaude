# EditorClaude

Editor automático de vídeo por fases. Fase 1: **rough cut** — remove silêncios, gaguejos, falsos começos e redundâncias de um vídeo bruto, sem intervenção manual.

## Começando do zero (guia para quem chegou agora)

### O que é isto, em 30 segundos

Este repositório é um pipeline de edição de vídeo operado por IA. A ideia central:
scripts Python fazem o trabalho pesado (transcrever, decidir cortes, renderizar) e
o **Claude Code** atua como operador — você abre o Claude Code na pasta do projeto,
pede "edita esse vídeo", e ele executa o fluxo inteiro sozinho, porque o repositório
já ensina a ele como trabalhar:

- `.claude/skills/rough-cut/` — a "receita" que o Claude Code segue ao editar um
  vídeo (ordem dos passos, preset do canal, o que nunca fazer).
- `.mcp.json` — dá ao Claude Code acesso direto ao Premiere Pro (opcional, ~280
  ferramentas via MCP).
- `styles/seco.json` — o estilo do canal (agressividade do corte, áudio, cor,
  plataformas de saída). Fonte única de verdade: mudou o estilo, muda aqui.

Você NÃO precisa do Premiere para usar o projeto — o caminho padrão renderiza
mp4 direto com ffmpeg. O Premiere é uma saída alternativa para quem quer
continuar a edição manualmente numa timeline.

### O que você precisa ter instalado

| Ferramenta | Para quê | Como instalar |
|---|---|---|
| macOS + [Homebrew](https://brew.sh) | os caminhos do projeto assumem Mac | — |
| ffmpeg | extração de áudio, render, loudness | `brew install ffmpeg` |
| Python 3.11+ | roda o pipeline (testado com 3.11.8) | `brew install python@3.11` ou pyenv |
| [Claude Code](https://claude.com/claude-code) | o operador do pipeline | `npm install -g @anthropic-ai/claude-code` |
| Node.js 18+ | *(opcional)* só para o MCP do Premiere | `brew install node` |
| Adobe Premiere Pro | *(opcional)* saída em timeline editável | Creative Cloud |

### Instalação

```bash
git clone https://github.com/lfelipebessa/editorClaude.git
cd editorClaude

# venv + dependências (WhisperX puxa PyTorch — a instalação demora alguns minutos)
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# teste rápido: deve imprimir a ajuda do transcritor
.venv/bin/python src/transcribe.py --help
```

Na **primeira transcrição** o WhisperX baixa os modelos (~2–3 GB, uma vez só).
Roda em CPU; num Apple Silicon um vídeo de ~10 min transcreve em poucos minutos.

### Como usar com o SEU Claude Code

```bash
cd editorClaude
claude
```

Na primeira vez o Claude Code pergunta se você confia no `.mcp.json` do projeto —
aprove (ou recuse, se não for usar o Premiere; o resto funciona igual). Depois é
conversa:

> edita esse vídeo: ~/Downloads/video_bruto.mp4

A skill `rough-cut` assume e executa o fluxo do canal: acelera 1.2x → transcreve
em pt → gera a cut-list com o preset `seco` → renderiza para `~/Downloads`, com
áudio normalizado e cor aplicada. Você também pode pedir variações:

> faz a versão vertical pra Reel
> monta a timeline no Premiere em vez de renderizar mp4
> deixa o corte menos agressivo

Para mudanças de estilo permanentes, peça para ele editar `styles/seco.json` —
nunca ajuste parâmetros inline (regra da skill).

Prefere rodar na mão, sem Claude? Todos os comandos estão na seção **Uso** abaixo.

### Setup opcional: Premiere Pro via MCP

O servidor MCP do Premiere vive em `vendor/Adobe_Premiere_Pro_MCP` e **não vem
no clone** (é gitignored). Para habilitar:

```bash
git clone https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP vendor/Adobe_Premiere_Pro_MCP
cd vendor/Adobe_Premiere_Pro_MCP && npm install && npm run build
```

Ajuste o caminho absoluto em `.mcp.json` para a sua máquina e siga o setup único
dentro do Premiere (instalar a extensão CEP e iniciar o painel MCP Bridge):
passo a passo em [`adapters/premiere_mcp/README.md`](adapters/premiere_mcp/README.md),
que também documenta todas as fragilidades conhecidas do bridge.

### Verificando que está tudo funcionando

Os testes são scripts standalone (sem pytest) — cada arquivo roda direto:

```bash
# heurísticas de corte, com transcript sintético (não precisa de vídeo nem Premiere)
.venv/bin/python tests/test_cutlist.py

# testes que precisam de vídeo usam um fixture gerado por ffmpeg:
tests/make_fixture.sh
```

## Pipeline

```
vídeo bruto ──▶ src/transcribe.py ──▶ transcript.json (timestamps por palavra, WhisperX)
                                          │
                                          ▼
                                    src/cutlist.py ──▶ cutlist.json (segmentos a manter)
                                          │
              ┌───────────────────────────┴──────────────────────┐
              ▼                                                  ▼
  adapters/render_ffmpeg.py                        adapters/premiere_mcp/ (esqueleto)
  rough_cut.mp4 (funciona hoje)                    timeline no Premiere (bloqueado)
```

O núcleo (`src/`) é agnóstico de editor: produz apenas o transcript e a cut-list.
Os adaptadores (`adapters/`) consomem a cut-list e materializam o corte em um destino específico.

O transcript JSON inclui, além dos segmentos com palavras, um campo `silences`
(spans detectados no áudio via ffmpeg `silencedetect`). Ele existe porque o aligner
do WhisperX às vezes estica uma palavra por cima de uma pausa longa, fazendo o
silêncio sumir dos timestamps — o `cutlist.py` usa os `silences` como cortes
obrigatórios, independentes do texto.

## Uso

```bash
source .venv/bin/activate

# 1. Transcrever (extrai áudio com ffmpeg + WhisperX word-level)
python src/transcribe.py video.mp4 -o output/transcript.json

# 2. Gerar cut-list
python src/cutlist.py output/transcript.json -o output/cutlist.json

# 2b. Corte agressivo estilo rede social (jump cut seco)
python src/cutlist.py output/transcript.json --preset seco -o output/cutlist.json
# ou ajuste fino: --trim-start 0.07 --trim-end 0.12 --max-word-gap 0.25
#   trim-start/trim-end: segundos cortados DENTRO da fala nas bordas de cada segmento
#   max-word-gap: pausa entre palavras acima da qual vira corte (default 0.8s)
#
# O trim de borda é adaptativo à duração do segmento E da palavra da borda:
#   duração < trim_min_duration      -> trim zero (palavra curta isolada sai intacta)
#   cada borda perde no máximo trim_max_fraction da duração do segmento
#     e trim_max_word_fraction da duração da palavra daquela borda
#   palavra da borda < min_word_protect -> trim zero naquela borda (nunca truncar palavra)
#   palavra final curta/sigla ("CRM")   -> fim estende até o silêncio real detectado
#     (aligner fecha siglas cedo demais), teto short_word_end_margin
#   segmentos longos com palavras longas nas bordas -> trim_start/trim_end na íntegra
#
# Presets vivem em styles/<nome>.json (fonte única de verdade, versionada).
# styles/seco.json também define as plataformas de saída (16:9 / 9:16).

# 3b. Variante vertical 9:16 (Instagram/TikTok): crop central definido no style,
#     ajuste o enquadramento com --crop-x-offset (px do vídeo fonte, + = direita)
python adapters/render_ffmpeg.py video.mp4 output/cutlist.json --platform instagram -o output/rough_cut_vertical.mp4

# Áudio: se o style tem a seção "audio", o render aplica automaticamente
# loudnorm em duas passadas (medição + ganho linear) e hard limiter, com alvos
# do style (seco: I=-14 LUFS, TP=-1.5 dBTP, LRA=7 — padrão de rede social para
# fala). Desligar com --no-audio-norm.

# 3. Renderizar rough cut
python adapters/render_ffmpeg.py video.mp4 output/cutlist.json -o output/rough_cut.mp4
```

## Contrato: formato da cut-list (JSON)

A cut-list é o contrato central do projeto. Todo adaptador de saída consome exatamente este formato e nada mais — nenhum adaptador lê o transcript diretamente.

```json
{
  "version": 1,
  "source": {
    "path": "/caminho/absoluto/video.mp4",
    "duration": 132.48
  },
  "segments": [
    {
      "start": 1.84,
      "end": 7.02,
      "text": "fala contida no segmento",
      "reason": "speech"
    }
  ],
  "removed": [
    {
      "start": 0.0,
      "end": 1.84,
      "reason": "silence",
      "text": ""
    }
  ],
  "stats": {
    "kept_duration": 98.7,
    "removed_duration": 33.78,
    "segment_count": 12
  }
}
```

Regras do contrato:

- **`version`** — inteiro; incrementa em toda mudança incompatível do formato.
- **`settings`** — opcional, informativo: os parâmetros usados na geração (preset, trims, gaps). Adaptadores devem ignorar.
- **`source.path`** — caminho absoluto do vídeo original; `source.duration` em segundos.
- **`segments`** — trechos a MANTER, na ordem de saída. Tempos em segundos (float), relativos ao vídeo original. Segmentos são não sobrepostos, ordenados por `start`, e já incluem o padding de respiro — o adaptador não adiciona margens.
- **`removed`** — trechos descartados, apenas para auditoria/debug. `reason` ∈ `silence` | `stutter` | `false_start` | `repetition` | `filler`. Adaptadores devem ignorar este campo.
- **`stats`** — informativo, opcional.

Um adaptador correto: concatena os `segments` na ordem dada, cortando o vídeo original em `[start, end)` de cada um. Nada além disso.

## Estrutura

```
src/            núcleo agnóstico de editor
  transcribe.py   vídeo → transcript.json (WhisperX, word-level)
  cutlist.py      transcript.json → cutlist.json
adapters/       saídas
  render_ffmpeg.py   cut-list → rough_cut.mp4 (ffmpeg)
  compose_ffmpeg.py  bruto + cut-list + motion-manifest [+ SRT] → Reel 1080x1920
                     (motion MotionSkills em cima, câmera 9:8 gradada embaixo,
                     legendas na divisa; ver src/compose.py para o resolvedor
                     de âncoras textuais e o SRT editável)
  premiere_mcp/      esqueleto do adaptador Premiere Pro MCP (não instalado)
tests/          testes
```

## Requisitos

- Python 3.11+ com venv em `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)
- ffmpeg em `/opt/homebrew/bin/ffmpeg`
- WhisperX (instalado no venv)

## Fases futuras

- Fase 2: presets de áudio (amplify + hard limiter), adjustment layers, grain, transições.
- Fase 3: integração MotionSkills + variantes 16:9 (YouTube) e 9:16 (Instagram/TikTok).

# Cor (Fase 2 bloco 2)

Seção `color` do style: LUT opcional (`lut3d`, só para footage D-Log M 10-bit vinda do cartão SD — a LUT oficial já está em `assets/luts/dji_dlogm_to_rec709_v1.cube`; o export do app Mimo entrega sempre 8-bit Rec.709 e NÃO leva LUT) + grade via `curve_s` (curva S no filtro `curves`), `vibrance`, `exposure` e `eq`. Aplicada apenas a footage de câmera (`scope: camera`) — motion graphics nunca passam pela cadeia de cor. `--no-color` desliga. Previews lado a lado: ver `~/Downloads/color_preview/`.
