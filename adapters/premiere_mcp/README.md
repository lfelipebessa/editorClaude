# Adaptador Premiere Pro MCP

**Status: implementado. Aguarda passos manuais do usuário no Premiere (uma vez).**

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
