# EditorClaude — operador

Pipeline de edição do canal operado por Claude Code. A receita completa está na
skill `.claude/skills/rough-cut/` — invocá-la sempre que o pedido for editar,
cortar ou compor vídeo. Setup, comandos manuais e formatos: `README.md`.

## Papel no pipeline do canal (fluxo com checkpoints)

Este repo é o dono da FONTE DE VERDADE DO CORTE. No fechamento do CHECKPOINT 1
(usuário aprova o corte na timeline), `export_cut.py` persiste:

- `output/cutlist_final_<slug>.json` — o corte real, re-renderizável sem Premiere
- `output/transcript_cut_<slug>.json` — fala remapeada pro tempo do corte
  (score, silences, offsets corte↔fonte, `source.speed_rate`)

O contrato pro MotionSkills é o `output/handoff_<slug>.md`
(`prepare_motion_handoff.py` — fala real + grafia da copy + marcadores TELA).
O brief de motion NUNCA nasce da copy pré-gravação quando existe handoff.
No CHECKPOINT 2, `diff_copy.py` compara copy aprovada × fala real — trava de
publicação (CTA, fosso, keyword). Timestamps de fonte referem-se ao arquivo
transcrito (na prática o `_12x`; o fator vive em `source.speed_rate`).

## Contexto canônico

Decisão criativa/de negócio → ler o vault (herdado do CLAUDE.md de
`~/development`): `~/development/2Cerebro/99 Contexto/`.
