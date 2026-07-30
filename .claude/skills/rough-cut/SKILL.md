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
   O áudio é normalizado automaticamente pela seção `audio` do style (loudnorm
   2 passadas + hard limiter; alvos I=-14 LUFS / TP=-1.5 dBTP / LRA=7). Alvos de
   loudness são estilo do canal: mudam em `styles/seco.json`, nunca no código.

   A cor também é padrão do canal (seção `color` do style): LUT opcional (só
   quando o footage vier em D-Log M — o Pocket 3 em perfil Normal NÃO leva LUT)
   + ajustes pós (exposure/contrast/saturation). **Cor é SÓ para footage de
   câmera** (`scope: camera`) — motion graphics nunca recebem tratamento de cor.
   Desligar com --no-color.

   **(b) timeline no Premiere Pro (MCP)** — requer Premiere aberto com o painel
   `MCP Bridge (CEP)` iniciado (setup único: adapters/premiere_mcp/README.md):
   ```bash
   .venv/bin/python adapters/premiere_mcp/render_premiere.py <video> output/cutlist_<slug>.json --project-name EditorClaude_<slug> --no-color
   ```
   Cria projeto NOVO — nunca tocar em projetos existentes do usuário.
   `--no-color` é o padrão do canal no Premiere: a grade completa (com as
   curvas feitas à mão) vem de Paste Attributes a partir da sequência de
   referência `rough_cut_dji_v4_audio` (projeto EditorClaude_teste). Colar
   Lumetri em clipe que já tem Lumetri DOBRA a grade — por isso a timeline
   nasce limpa de cor. Sem `--no-color` só quando o usuário não for usar a
   referência (aí a grade escalar do style entra por script).
   - `<slug>`: identificador curto derivado do nome do arquivo + data (ex.: `dji_20260729`).
   - `vN`: v1, v2... — nunca sobrescrever uma versão anterior; o usuário compara versões.
   - Variante vertical (Instagram/TikTok): adicionar `--platform instagram` (ou `tiktok`)
     — o crop 9:16 vem da seção `platforms` de `styles/seco.json`. Antes de renderizar
     vertical, extrair 1 frame do meio e conferir o enquadramento do rosto; ajustar
     `--crop-x-offset` se necessário.

3b. **Reel composto com motion graphics** — quando existir dir do vídeo no
   MotionSkills (`~/development/MotionSkills/motion-graphics/src/videos/<nome>/`
   com `brief.md` e clips renderizados em `out/<nome>/clips/`), este é o
   FORMATO PADRÃO do Reel: motions em cima, câmera embaixo, legendas na divisa.

   ```bash
   # 1. cola: manifest resolvido (âncoras textuais do brief) + SRT MAIÚSCULO
   .venv/bin/python src/prepare_compose.py output/transcript_<slug>.json output/cutlist_<slug>.json ~/development/MotionSkills/motion-graphics/src/videos/<nome>
   # 2. REVISAR o SRT contra o brief (transcrição erra: cloud->Claude,
   #    admira->ADMIN...) — corrigir SÓ texto, nunca timestamps
   # 3. timeline editável no Premiere — SAÍDA PADRÃO (o usuário sempre ajusta
   #    antes de exportar; decisão de 2026-07-30):
   .venv/bin/python adapters/premiere_mcp/compose_premiere.py <video> output/cutlist_<slug>.json output/motion_manifest_<slug>.json --srt output/captions_<slug>.srt --sequence-name reel_<slug>
   ```
   O mp4 automático (compose_ffmpeg, mesmos argumentos + `-o ~/Downloads/
   reel_<slug>.mp4`) NÃO roda por padrão — só quando o usuário pedir preview
   rápido ou publicação direta sem ajustes.
   Após o compose_premiere, aplicar a grade nos clipes de V2 (track_index=1)
   com build_lumetri_jsx + noise_from_style. O enquadramento padrão da câmera
   (cabeça quase encostando na divisa: Scale 58, Position [0.58, 0.6825] +
   Crop Top 22.03% para fonte 4K 16:9) já sai do camera_transform do próprio
   compose_premiere — conferir por frame exportado (cabeça a ~20-35px da
   divisa). Avisar o usuário dos toques manuais: estilo/posição da caption
   track (divisa, y≈960) e, se quiser as curvas finas, Remove Attributes +
   Paste Attributes da referência em V2 (NUNCA marcar Motion nem Crop).

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
