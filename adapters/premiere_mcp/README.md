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

## Cor via MCP (IMPLEMENTADO 2026-07-30 — E2E validado, 23 clipes)

A seção `color` do style vira **Lumetri Color por clipe**, editável no painel
Lumetri depois (`--style seco` por padrão; `--no-color` desliga). Mapeamento em
`lumetri_from_style`: exposure_ev → Exposure (stops); vibrance → Vibrance
(×100); curve_s → Shadows/Highlights (desvio dos pontos ×400) + Contrast
(inclinação do trecho central); eq → Contrast/Saturation. Aproximação visual —
Lumetri ≠ filtros do ffmpeg; recalibrar no olho se o style mudar muito.

Aplicação é UM `execute_extendscript` em lote (`build_lumetri_jsx`) para a
track inteira — por clipe seriam 5×N round-trips. O JSX é idempotente: reusa
Lumetri existente no clipe em vez de empilhar outro.

Fragilidades descobertas no E2E de cor:

- **Adjustment layer real é impossível por script**: `app.project.
  createAdjustmentLayer` e o equivalente QE não existem no Premiere 2026. A
  tool `add_adjustment_layer` do vendor "funciona" criando um **PNG
  transparente** — armadilha: efeito sobre PNG transparente NÃO propaga para
  as camadas de baixo; a grade fica silenciosamente invisível. Por isso a cor
  é por clipe.
- `remove_effect_by_name` não funciona (componentes não expõem remove/delete
  no ExtendScript) — daí a necessidade do JSX idempotente.
- `execute_extendscript` embrulha o script numa função: sem `return` o
  resultado vem `"undefined"`. E a resposta é string JSON dupla-codificada —
  `parse_tool_payload` do adaptador tolera payload não-dict.
- displayNames do Lumetri vêm em inglês (Exposure/Contrast/Shadows/...) neste
  install; propriedades repetem nome entre seções (Saturation em Basic e
  Creative) — o JSX usa guard para setar só a primeira ocorrência.
- **Replicar grade entre clipes**: `build_copy_effects_jsx` copia por índice
  (a tool do vendor casa por displayName e erra em propriedades sem nome/
  duplicadas) e cobre TODOS os escalares + Sharpen + Noise. **Limite duro da
  API**: RGB Curves por canal e Hue Saturation Curves do Lumetri NÃO existem
  em nenhuma propriedade enumerável do ExtendScript — vivem só no estado
  interno do efeito (o param "Blob" é snapshot defasado, não fonte). Color
  pickers (White Balance, Set/Add/Remove color, seletores Hue-vs) divergem e
  IGNORAM setValue (testado: grava e relê o valor antigo). Consequência:
  grade que usa curvas/HSL só replica via **Paste Attributes nativo**
  (Cmd+C no clipe fonte -> selecionar alvos -> Cmd+Opt+V marcando Lumetri
  Color e Noise). O adaptador automatiza o resto; curvas finas são passo
  manual único por timeline.
- **Paste Attributes EMPILHA efeitos homônimos** (não substitui): colar
  Lumetri num clipe que já tem Lumetri = grade dobrada. Fluxo do canal com
  grade de referência (curvas feitas à mão): montar a timeline com
  `--no-color` e colar da referência — OU, se a timeline já nasceu com cor
  por script, Remove Attributes (Lumetri Color + Noise) nos alvos ANTES de
  colar. Não há remoção de efeito via API; a limpeza é sempre nativa.
- O efeito **Noise do Premiere 2026 é o novo, estilo film grain**
  (Intensity/Shadows/Midtones/Highlights/Saturation/Blend Mode) — o clássico
  "Amount of Noise" não existe mais. Grain do finish vira Intensity (grain×3)
  + Saturation 0 (só luma). Atenção: só adicionar o efeito deixa Intensity 50
  (default bem visível); sempre setar o valor na mesma passada.

Consome a cut-list JSON (contrato no README da raiz) e monta a timeline no
Premiere Pro: cria projeto novo, importa o vídeo fonte, cria sequência e coloca
um subclip `[start, end)` por segmento, na ordem, via `add_to_timeline_batch`.
Mesmo contrato do adaptador ffmpeg — este adaptador não decide corte, só executa.

## Composer vertical editável (compose_premiere.py)

Consome cut-list + motion-manifest + SRT (mesmos contratos do
`compose_ffmpeg.py`) e monta o Reel como TIMELINE: sequência 1080x1920 criada
de um clipe de motion (herda formato sem diálogo), V1 = motions full-frame nos
tempos resolvidos, V2 = câmera com Motion Scale/Position na metade de baixo
(JSX em lote), caption track do SRT via `import_media` + `create_caption_track`
(texto corrigível no painel Captions; posição/estilo do track = ajuste único no
Essential Graphics). Cor: Paste Attributes da referência em V2 (NUNCA marcar
Motion). E2E validado 2026-07-30: 6 motions + 27 cortes + captions.

Fragilidade extra: `export_frame` interpreta `time` numa unidade não-linear
(não é segundos nem frames×fps de forma consistente) — para conferência
visual, exportar vários pontos e validar pela CONSISTÊNCIA cena↔legenda, não
pelo timestamp pedido.

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
