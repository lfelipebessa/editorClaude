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

3b. **Reel composto com motion graphics** — FORMATO PADRÃO do Reel do canal:
   motions em cima, câmera embaixo, legendas na divisa. Desde 2026-08-05 os
   motions NASCEM DO CORTE APROVADO (spec 2026-08-04-motion-checkpoint): não
   existe mais gerar motion da copy antes da gravação — o dir do vídeo no
   MotionSkills é criado no meio deste fluxo, a partir do handoff.

   **Metodologia em ETAPAS com checkpoints do usuário (padrão desde
   2026-07-31; handoff desde 2026-08-05): CORTE → checkpoint → HANDOFF →
   geração no MotionSkills (paralela) → MOTIONS+MÚSICA → checkpoint + cor
   manual → LEGENDAS por último.** O corte automático sempre precisa de
   ajuste fino humano, e legenda por último absorve qualquer retoque:

   ```bash
   # 1. ETAPA CORTE: timeline só com câmera + voz, SEM manifest (clips de
   #    motion ainda não existem — V1 vazia -> Close Gap funciona)
   .venv/bin/python adapters/premiere_mcp/compose_premiere.py <video> output/cutlist_<slug>.json --sequence-name reel_<slug> --somente-corte
   # 2. CHECKPOINT: usuário edita o corte e avisa quando fechou
   # 3. HANDOFF (corte aprovado -> MotionSkills): lê o corte FINAL da
   #    timeline, mescla com a copy do vault (grafia + TELA:) e gera
   #    output/handoff_<slug>.md
   .venv/bin/python src/prepare_motion_handoff.py output/transcript_<slug>.json --copy "<nota de copy no 2Cerebro>" --sequence-name reel_<slug>
   #    -> na nota de copy do vault: frontmatter ganha status:
   #       entregue-ao-pipeline e o slug (campos que o template já prevê)
   #    -> convenção da copy: TELA: escrito imediatamente APÓS a frase sobre
   #       a qual o texto deve aparecer (a âncora são as palavras ANTERIORES
   #       ao marcador; TELA antes da frase cai um bloco cedo). Antes de
   #       enviar, conferir as linhas TELA: do handoff — cada uma pertence ao
   #       bloco ACIMA; checagem de 10s que evita re-render.
   #    -> enviar o handoff (com o relatório de Divergências) ao Produtor
   #       de Video do MotionSkills via Maestri; agente DESSELECIONADO no
   #       canvas; geração (brief -> cenas -> render) roda em paralelo —
   #       seguir o fluxo quando os clips chegarem (maestri notify)
   # 4. cola (SÓ depois dos clips chegarem): manifest resolvido + SRT
   .venv/bin/python src/prepare_compose.py output/transcript_<slug>.json output/cutlist_<slug>.json ~/development/MotionSkills/motion-graphics/src/videos/<nome>
   # 5. REVISAR o SRT contra o HANDOFF (transcrição erra: cloud->Claude,
   #    admira->ADMIN...) — corrigir SÓ texto, nunca timestamps
   # 6. ETAPA MOTIONS: lê o corte FINAL da timeline e sobe motions fatiados
   #    nos cortes reais + música aparada ao fim do conteúdo + punch-ins
   #    automáticos (punch_in.count no style, padrão 3 desde 2026-08-06):
   #    o de abertura no 1º clipe da câmera E do motion (Scale 120 ABSOLUTO
   #    assentando na base de cada um em 0.4s, blur só na câmera) e os
   #    extras SÓ na câmera, nos cortes mais próximos de 1/3 e 2/3 do
   #    conteúdo — pedido do usuário 2026-08-06: punch em TODO corte cansa,
   #    3 pontos distribuídos dão o dinamismo certo
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa motions
   # 7. CHECKPOINT: usuário revisa o dinamismo; COR entra aqui, manual:
   #    Paste Attributes da referência em V2 (NUNCA marcar Motion/Crop)
   # 8. ETAPA LEGENDAS (sempre a última — lê o áudio ATUAL da timeline):
   .venv/bin/python adapters/premiere_mcp/finalize_premiere.py output/transcript_<slug>.json output/motion_manifest_<slug>.json --sequence-name reel_<slug> --etapa legendas --corrected-srt output/captions_<slug>.srt
   # 9. QA DA LEGENDA (sempre rodar após a etapa legendas): re-transcreve o
   #    áudio do corte final e diffa com a legenda — pega frase que o ASR
   #    ENGOLIU no bruto (ex.: "Terminei a call" virou a palavra falsa "Eu";
   #    palavra que não existe no transcript nunca vira legenda). Diff tem
   #    ruído em borda de corte; sinal forte = os dois ASRs discordando da
   #    MESMA região. Frase engolida: inserir palavras no transcript (com os
   #    timestamps de fonte que o QA imprime), tokens no SRT corrigido, e
   #    refazer com recaption.
   .venv/bin/python adapters/premiere_mcp/qa_captions_premiere.py <video> output/captions_reel_<slug>_final.srt --sequence-name reel_<slug>
   # 10. ARQUIVAR NO VAULT (fecha o ciclo com o 2Cerebro): nota de resultado
   #    seguindo 98 Templates/ e 99 Contexto/arquitetura-do-vault.md — NUNCA
   #    inventar estrutura nova. A nota linka [[copy]], traz o transcript
   #    real do corte (texto corrido dos blocos do handoff), o brief e os
   #    caminhos dos artefatos locais. Métrica NÃO entra (é assunto do
   #    EstudoConteudo/Supabase — regra do template).
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
   prepare_compose (flag é legado para reprocessar sets antigos). **Única
   exceção (2026-08-04): o punch-in de abertura** — keyframes de Scale por
   cima do transform autorado, só no 1º clipe, aplicados pelo finalize.
   ATENÇÃO ao aplicar keyframe via MCP na mão: o tempo ancora na MÍDIA
   (somar o inPoint do clipe); keyframe antes do inPoint não renderiza.

   **Música de fundo é padrão** (seção `music` do style): entra automática nos
   dois composers — `musicafundo3` da biblioteca `assets/music/`, ganho
   calculado por medição para o bed cair em `bed_lufs` (-28 LUFS ≈ 14 dB
   abaixo da voz; histórico: -30 estava baixo demais [2026-07-31], -25 alto
   demais [2026-08-06] — o ponto do canal vive entre os dois). Trocar: `--music <nome>` (meAndTheD, musicafundo,
   musicafundo2); desligar: `--no-music`. Música nova = jogar o arquivo em
   `assets/music/*.m4a` (extrair de mp4: `ffmpeg -i in.mp4 -vn -c:a copy
   out.m4a`) — o ganho se autocalibra pela medição. No Premiere ela entra em
   A2 cortada no fim do vídeo com o ganho no clipe (fade out manual, se quiser).
   Na etapa de cor (passo 7), se o usuário não for usar a referência, a
   grade escalar entra por script nos clipes de V2 (track_index=1) com
   build_lumetri_jsx + noise_from_style. O enquadramento padrão da câmera
   (cabeça quase encostando na divisa: Scale 58, Position [0.58, 0.6825] +
   Crop Top 22.03% para fonte 4K 16:9) já sai do camera_transform do próprio
   compose_premiere — conferir por frame exportado (cabeça a ~20-35px da
   divisa). Avisar o usuário dos toques manuais: (1) na caption track nova,
   aplicar o **Track Style `canal`** (dropdown Track Style no Essential
   Graphics — estilo salvo pelo usuário: **Open Sans Bold** (desde
   2026-08-06, antes Arial Black), maiúsculas, **tamanho 70**, branco com
   contorno preto, **centralizada no Align & Transform**; tamanho 70 desde
   2026-08-04, antes era 62 apoiada na divisa) — 2 cliques. Estilizar
   caption por script NÃO dá: nem o MCP nem o ExtendScript expõem estilo
   de caption — o Track Style salvo é o único atalho, por isso mudança de
   fonte = re-salvar o Track Style `canal` uma vez no Premiere.
   No burn ffmpeg o mesmo padrão sai da seção `captions` do style
   (font_file Open Sans Bold, size 70); (2) se quiser as
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
