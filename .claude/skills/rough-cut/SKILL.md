---
name: rough-cut
description: Fluxo padrão para gerar rough cut de um vídeo bruto do canal — transcrição pt, corte com preset seco (padrão do canal), render para ~/Downloads. Use sempre que o usuário pedir para editar/cortar um vídeo.
---

# Rough cut — fluxo padrão do canal

**O preset `seco` é o padrão do canal.** Nunca invente parâmetros de corte, nunca
ajuste valores inline. Toda mudança de estilo (trims, gaps, plataformas) é feita
editando `styles/seco.json` — fonte única de verdade, versionada no git.

O trim de borda é **adaptativo à duração do segmento E da palavra da borda**
(regra em `apply_edge_trims`, valores no style):
- segmento abaixo de `trim_min_duration` não recebe trim algum;
- cada borda perde no máximo `trim_max_fraction` da duração do segmento e
  `trim_max_word_fraction` da duração da palavra daquela borda;
- palavra da borda mais curta que `min_word_protect` → trim zero naquela borda
  (palavra nunca sai truncada);
- palavra final curta/sigla (ex.: "CRM"): o aligner costuma fechá-la antes da fala
  acabar — o fim estende até o silêncio real detectado, com teto
  `short_word_end_margin`, sem nunca invadir o segmento seguinte;
- segmento longo com palavras longas nas bordas → `trim_start`/`trim_end` na íntegra.

## Fluxo (executar do diretório do projeto, com `.venv` ativo)

Dado um vídeo bruto `<video>`:

1. **Transcrever** — PULE este passo se já existir transcript do vídeo em `output/`
   (transcrição é a etapa cara; nunca re-transcrever sem necessidade):
   ```bash
   .venv/bin/python src/transcribe.py <video> -o output/transcript_<slug>.json --language pt
   ```
   Sempre `--language pt` (detecção automática erra em clipes curtos).

2. **Cut-list** com o preset padrão:
   ```bash
   .venv/bin/python src/cutlist.py output/transcript_<slug>.json --preset seco -o output/cutlist_<slug>.json
   ```

3. **Render** — duas saídas disponíveis; mp4 direto é o default, timeline no
   Premiere quando o usuário pedir para continuar a edição lá:

   **(a) mp4 direto (ffmpeg):**
   ```bash
   .venv/bin/python adapters/render_ffmpeg.py <video> output/cutlist_<slug>.json -o ~/Downloads/rough_cut_<slug>_vN.mp4
   ```

   **(b) timeline no Premiere Pro (MCP)** — requer Premiere aberto com o painel
   `MCP Bridge (CEP)` iniciado (setup único: adapters/premiere_mcp/README.md):
   ```bash
   .venv/bin/python adapters/premiere_mcp/render_premiere.py <video> output/cutlist_<slug>.json --project-name EditorClaude_<slug>
   ```
   Cria projeto NOVO — nunca tocar em projetos existentes do usuário.
   - `<slug>`: identificador curto derivado do nome do arquivo + data (ex.: `dji_20260729`).
   - `vN`: v1, v2... — nunca sobrescrever uma versão anterior; o usuário compara versões.
   - Variante vertical (Instagram/TikTok): adicionar `--platform instagram` (ou `tiktok`)
     — o crop 9:16 vem da seção `platforms` de `styles/seco.json`. Antes de renderizar
     vertical, extrair 1 frame do meio e conferir o enquadramento do rosto; ajustar
     `--crop-x-offset` se necessário.

4. **Reportar** ao final, sempre:
   - duração original vs final;
   - número de segmentos mantidos e cortes por motivo (silence, stutter, false_start,
     repetition, filler — contar em `removed` da cut-list);
   - qualquer problema novo que o footage revelou.

## Regras

- Transcript e cut-list ficam em `output/` (gitignored); vídeo renderizado vai para
  `~/Downloads` com o nome acima para o usuário achar fácil.
- Nunca commitar vídeo nem artefatos grandes.
- Código só muda se o pipeline quebrar ou ganhar capacidade nova — gosto de corte
  NÃO é código, é `styles/seco.json`.
