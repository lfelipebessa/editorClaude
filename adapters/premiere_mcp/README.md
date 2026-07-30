# Adaptador Premiere Pro MCP (esqueleto)

**Status: BLOQUEADO — o Adobe Premiere Pro não está instalado nesta máquina.**
Nada deste diretório deve ser instalado ou executado até o Premiere existir aqui.

## O que este adaptador fará

Consumir a cut-list JSON (contrato no README da raiz) e montar uma sequência no
Premiere Pro via MCP, com um clipe por segmento, na ordem da cut-list — em vez de
renderizar um mp4 como o adaptador ffmpeg.

## Dependência externa

- MCP server: <https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP>
  (controla o Premiere via UXP/ExtendScript; requer Premiere Pro instalado e aberto)

## Plano de implementação (quando desbloquear)

1. Instalar o MCP server do repositório acima e registrá-lo no cliente MCP.
2. `render_premiere.py`: ler a cut-list, criar projeto/sequência, importar o vídeo
   original e inserir subclips `[start, end)` de cada segmento na timeline.
3. Mesma interface de linha de comando do adaptador ffmpeg:
   `python adapters/premiere_mcp/render_premiere.py video.mp4 cutlist.json`
