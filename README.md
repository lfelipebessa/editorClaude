# EditorClaude

Editor automático de vídeo por fases. Fase 1: **rough cut** — remove silêncios, gaguejos, falsos começos e redundâncias de um vídeo bruto, sem intervenção manual.

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
