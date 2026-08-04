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
- segmento longo com palavras longas nas bordas → `trim_start`/`trim_end` na íntegra;
- **borda de saída respira**: todo fim de segmento leva `pad_after` (0.15s desde
  2026-08-04) depois do onset do silêncio detectado — sem isso o corte fechava no
  disparo do silencedetect e comia o decay da última sílaba em parte dos clipes.
  Regra de calibragem: sobra de fim é recuperável na timeline, falta não é —
  na dúvida, errar sempre para o lado da sobra.

## Fluxo (executar do diretório do projeto, com `.venv` ativo)

Dado um vídeo bruto `<video>`:

0. **Acelerar 1.2x** (padrão do canal para Reel falado desde 2026-07-31 —
   Instagram pede fala veloz; taxa vive na seção `speed` de `styles/seco.json`):
   ```bash
   .venv/bin/python src/speedup.py <video>
   ```
   Gera `<video>_12x.mp4` ao lado do fonte, pitch preservado, fps mantido.
   **Daqui em diante TODO o fluxo usa o arquivo acelerado como `<video>`**
   (transcrição, corte, compose) — a aceleração vem ANTES da transcrição
   porque transcript, âncoras de motion e legendas referenciam timestamps do
   fonte; acelerar depois quebraria todos os mapeamentos. Pular só se o vídeo
   não for falado ou o usuário pedir ritmo natural. Motions do MotionSkills
   nunca aceleram (são autorados no próprio ritmo).

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

   **Metodologia em ETAPAS com checkpoints do usuário (padrão desde
   2026-07-31): CORTE → checkpoint → MOTIONS+MÚSICA → checkpoint + cor
   manual → LEGENDAS por último.** O corte automático sempre precisa de
   ajuste fino humano, e legenda por último absorve qualquer retoque das
   etapas anteriores sem precisar de recaption:

   ```bash
   # 1. cola: manifest resolvido (âncoras textuais do brief) + SRT MAIÚSCULO
   .venv/bin/python src/prepare_compose.py output/transcript_<slug>.json output/cutlist_<slug>.json ~/development/MotionSkills/motion-graphics/src/videos/<nome>
   # 2. REVISAR o SRT contra o brief (transcrição erra: cloud->Claude,
   #    admira->ADMIN...) — corrigir SÓ texto, nunca timestamps
   # 3. ETAPA CORTE: timeline só com câmera + voz (V1 vazia -> Close Gap
   #    funciona; usuário faz os ajustes manuais de corte com liberdade)
   .venv/bin/python adapters/premiere_mcp/compose_premiere.py <video> output/cutlist_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --somente-corte
   # 4. CHECKPOINT: usuário edita o corte e avisa quando fechou
   # 5. ETAPA MOTIONS: lê o corte FINAL da timeline e sobe motions fatiados
   #    nos cortes reais + música aparada ao fim do conteúdo
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa motions
   # 6. CHECKPOINT: usuário revisa o dinamismo; COR entra aqui, manual:
   #    Paste Attributes da referência em V2 (NUNCA marcar Motion/Crop)
   # 7. ETAPA LEGENDAS (sempre a última — lê o áudio ATUAL da timeline):
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa legendas --corrected-srt output/captions_<slug>.srt
   ```
   `--etapa tudo` (default do finalize) sobe motions+música+legendas de uma
   vez — usar só quando o usuário dispensar os checkpoints intermediários.
   Se o usuário editar DEPOIS do finalizar, refazer só a legenda com
   adapters/premiere_mcp/recaption_premiere.py (mesmos argumentos de
   transcript/--corrected-srt).
   O mp4 automático (compose_ffmpeg, mesmos argumentos + `-o ~/Downloads/
   reel_<slug>.mp4`) NÃO roda por padrão — só quando o usuário pedir preview
   rápido ou publicação direta sem ajustes.

   **Motion entra exatamente como autorado (padrão global desde 2026-07-31):**
   nunca ajustar posição, altura, X/Y ou zoom dos clipes de motion — eles já
   vêm no formato correto do MotionSkills. Não passar `--motion-y-px` no
   prepare_compose (flag é legado para reprocessar sets antigos).

   **Música de fundo é padrão** (seção `music` do style): entra automática nos
   dois composers — `musicafundo3` da biblioteca `assets/music/`, ganho
   calculado por medição para o bed cair em `bed_lufs` (-25 LUFS ≈ 11 dB
   abaixo da voz; ajustado de -30 em 2026-07-31 a pedido do usuário — estava
   baixo demais). Trocar: `--music <nome>` (meAndTheD, musicafundo,
   musicafundo2); desligar: `--no-music`. Música nova = jogar o arquivo em
   `assets/music/*.m4a` (extrair de mp4: `ffmpeg -i in.mp4 -vn -c:a copy
   out.m4a`) — o ganho se autocalibra pela medição. No Premiere ela entra em
   A2 cortada no fim do vídeo com o ganho no clipe (fade out manual, se quiser).
   Na etapa de cor (passo 6), se o usuário não for usar a referência, a
   grade escalar entra por script nos clipes de V2 (track_index=1) com
   build_lumetri_jsx + noise_from_style. O enquadramento padrão da câmera
   (cabeça quase encostando na divisa: Scale 58, Position [0.58, 0.6825] +
   Crop Top 22.03% para fonte 4K 16:9) já sai do camera_transform do próprio
   compose_premiere — conferir por frame exportado (cabeça a ~20-35px da
   divisa). Avisar o usuário dos toques manuais: (1) na caption track nova,
   aplicar o **Track Style `canal`** (dropdown Track Style no Essential
   Graphics — estilo salvo pelo usuário: maiúsculas, **tamanho 62, negrito**,
   branco com contorno preto, apoiada na divisa; padrão de fonte desde
   2026-07-31) — 2 cliques. No burn ffmpeg o mesmo padrão sai da seção
   `captions` do style (size 62; negrito vem da própria Arial Black); (2) se quiser as
   curvas finas, Remove Attributes + Paste Attributes da referência em V2
   (NUNCA marcar Motion nem Crop); (3) travar a track da música antes de
   editar (ripple não deve encolher o bed).

3c. **Export "lavado"/cinza vs preview = QuickTime gamma shift**, não defeito:
   o Premiere exibe Rec.709 a gamma 2.4 e o QuickTime do macOS a ~1.96 — o
   arquivo sai correto (conferir tags com ffprobe: bt709/bt709/bt709). Julgar
   cor no destino real (celular/Instagram, não QuickTime). Para o preview
   mostrar o look do QuickTime: Lumetri > Settings > Viewer Gamma 1.96 e só
   então retocar a grade. NUNCA compensar saturação/contraste às cegas com o
   viewer em 2.4.
   Para exportar JÁ compensado (grade da timeline intacta): LUTs do canal em
   `assets/luts/` — `qt_gamma_comp_50.cube` (padrão para Instagram: celular,
   que fica entre os dois gammas, bate com o preview) e `qt_gamma_comp_100.cube`
   (QuickTime do Mac bate com o preview). Aplicar SÓ no export: dialog de
   Export > Effects > Lumetri Look/LUT > Select > browse até o .cube. Nunca
   aplicar na timeline junto com o export-LUT (dobraria a compensação).

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
