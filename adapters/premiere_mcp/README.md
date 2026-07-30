# Adaptador Premiere Pro MCP

**Status: FUNCIONANDO — E2E validado em 2026-07-30 (27 clipes, 57.56s, 4K, Premiere 26.3).**

## Fragilidades conhecidas do bridge (aprendidas no E2E real)

- **NUNCA chamar `create_sequence`**: com preset vazio abre o diálogo modal
  "New Sequence" e congela TODO o scripting do Premiere até fechar na mão.
  O adaptador usa `create_sequence_from_clips` + `duplicate_sequence(clearContents)`.
- Qualquer tool que dispare UI modal trava o host sem erro identificável — o
  timeout de 45s do ExtendScript é a única pista. Não adianta re-tentar por
  software; alguém precisa fechar o diálogo no app.
- Respostas de tools nem sempre trazem o id esperado (`duplicate_sequence`);
  o adaptador tem fallbacks via `list_sequences`/`list_project_items`.
- `list_sequence_tracks` devolve os clipes mas com start/end zerados (quirk do
  bridge); use a duração da sequência em `list_sequences` para validação.
- Re-importar o mesmo arquivo cria itens duplicados no projeto (inofensivo).

## Efeitos de áudio via MCP (validado 2026-07-30)

FUNCIONA em Premiere 26.3: `adjust_audio_levels` (ganho em dB no componente
Volume do clipe) e `apply_effect` com `effectName: "Hard Limiter"` (inclusive
com `parameters: {"Maximum Amplitude": ...}`). Demo aplicada na sequência
`rough_cut_dji_v4_audio` do projeto de teste. Limitação: efeitos são por CLIPE
(não por track), então normalizar uma timeline inteira = um call por clipe —
e não há medição de loudness pelo Premiere (sem leitura de RMS/LUFS no
ExtendScript; o `detect_silence` do próprio MCP já usa ffmpeg por isso).
O caminho ffmpeg continua sendo o de precisão para loudness.

## Cor via MCP (investigado 2026-07-30, não implementado)

O servidor expõe `apply_lut` (clipId, lutPath absoluto .cube/.3dl, intensity
0-100) e `color_correct` (brightness/contrast/saturation/hue/highlights/
shadows/temperature/tint, escalas -100..100, por clipe). Não testados ao vivo —
usam o mesmo mecanismo de componentes que o Hard Limiter (que funcionou), então
a expectativa é positiva. Quando o caminho Premiere ganhar cor, mapear a seção
`color` do style para esses dois calls, clipe a clipe (mesma limitação do áudio:
não há efeito por track).

Consome a cut-list JSON (contrato no README da raiz) e monta a timeline no
Premiere Pro: cria projeto novo, importa o vídeo fonte, cria sequência e coloca
um subclip `[start, end)` por segmento, na ordem, via `add_to_timeline_batch`.
Mesmo contrato do adaptador ffmpeg — este adaptador não decide corte, só executa.

## Arquitetura

```
render_premiere.py ──MCP (JSON-RPC stdio)──▶ vendor/Adobe_Premiere_Pro_MCP (Node)
                                                   │ arquivos em /tmp/premiere-mcp-bridge
                                                   ▼
                                     painel "MCP Bridge (CEP)" dentro do Premiere
```

- MCP server: <https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP>, clonado em
  `vendor/Adobe_Premiere_Pro_MCP` (gitignored; re-clonar + `npm install && npm run build`
  se não existir).
- Extensão CEP instalada em `~/Library/Application Support/Adobe/CEP/extensions/MCPBridgeCEP`
  (CEP PlayerDebugMode já habilitado via `defaults write com.adobe.CSXS.*`).
- Registro MCP de escopo de projeto em `.mcp.json` (server `premiere-pro`) — qualquer
  agente do projeto ganha acesso às ~280 tools do servidor.

## Setup único no Premiere (manual, exige o app)

1. Salvar o trabalho e **reiniciar o Premiere Pro** (a extensão CEP carrega no start).
2. (Recomendado pelo guia oficial) `Preferences > Plugins > UXP Plugins > Enable developer mode`.
3. `Window > Extensions > MCP Bridge (CEP)`.
4. `Temp Directory` = `/tmp/premiere-mcp-bridge` → `Save Configuration` → `Start Bridge`
   → `Test Connection`.

## Uso

```bash
.venv/bin/python adapters/premiere_mcp/render_premiere.py video.mp4 output/cutlist.json \
    --project-name EditorClaude_teste --sequence-name rough_cut
# --dry-run mostra o plano sem tocar no Premiere
```

Cria sempre projeto NOVO (default `~/Documents/EditorClaude_teste`) — nunca toca
em projetos existentes.
