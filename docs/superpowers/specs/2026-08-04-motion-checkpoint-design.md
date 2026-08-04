# Centralização dos motions no checkpoint de corte

Data: 2026-08-04 · Status: aprovado pelo usuário (brainstorm da mesma data)

## Problema

Hoje os motion graphics nascem da **copy** (intenção), coladas manualmente numa
sessão do Claude Code no MotionSkills **antes da gravação**. Na gravação o
usuário improvisa — troca palavras, muda frases — e o vídeo real diverge dos
motions (texto em tela errado, timing estimado a 150wpm em vez do falado).
A integração entre os dois repos é o próprio usuário colando texto.

## Solução em uma frase

Mover a geração dos motions para **depois do checkpoint de corte** do
EditorClaude, alimentada por um **handoff** que mescla o transcript WhisperX do
corte aprovado (timing e palavras reais) com a copy do 2Cerebro (grafia e
marcadores de intenção) — enviado ao MotionSkills por um agente Maestri.

## Decisões de calibragem (respostas do usuário)

1. **Papel da copy**: transcript + copy mesclados. O corte aprovado dá timing e
   conteúdo real; a copy entra como referência de correção (grafia de marcas,
   marcadores `TELA:`) — mesma lógica do `merge_corrected_text` das legendas.
   Motion nunca mostra palavra que o usuário não falou, mas escreve certo.
2. **Orquestração**: agente Maestri (`Produtor de Video`) no MotionSkills
   recebe o handoff via `maestri ask`; geração roda em paralelo à edição.
3. **2Cerebro**: integração completa de I/O — copy nasce no vault, pipeline lê
   de lá, resultados voltam como notas linkadas. O vault já está rodando; o
   motor de melhoria automática e o grafo são responsabilidade dele, não deste
   pipeline. Métricas ficam com o EstudoConteudo/Supabase (regra do template).

## Fluxo end-to-end

```
2Cerebro: nota de copy (status: trabalhada)
   │  usuário grava o vídeo
   ▼
EditorClaude: speedup 1.2x → transcribe → cutlist → ETAPA CORTE
   │  usuário ajusta o corte na timeline e aprova o CHECKPOINT
   ▼
src/prepare_motion_handoff.py  (NOVO)
   corte real + transcript WhisperX + copy do vault
   → output/handoff_<slug>.md  (blocos com tempo REAL + texto mesclado + TELA:)
   ▼
Maestro envia ao Produtor de Vídeo (MotionSkills) via maestri ask
   │  geração roda em PARALELO enquanto o usuário segue no Premiere
   ▼
MotionSkills: brief → cenas TSX → render clips   (fluxo atual, intocado)
   ▼
prepare_compose → ETAPA MOTIONS → checkpoint + cor → LEGENDAS → QA   (atual)
   ▼
Nota de resultado no vault com [[links]] (copy, transcript real, brief)
```

Única mudança de ordem no processo do usuário: motions deixam de ser gerados
antes da gravação e passam a nascer do corte aprovado. As etapas com
checkpoints do rough-cut (CORTE → MOTIONS → LEGENDAS) ficam onde estão.

## Componentes

### 1. `src/prepare_motion_handoff.py` (novo, EditorClaude)

Roda na aprovação do checkpoint de corte.

**Entradas:**
- Corte real: timeline do Premiere via MCP (caminho padrão — mesma leitura de
  clips do `finalize_premiere`, remap com `remap_words_by_clips`) ou
  `cutlist_<slug>.json` (fallback, `remap_words`).
- `output/transcript_<slug>.json` (WhisperX word-level).
- `--copy <caminho da nota no vault>` (markdown com a copy e marcadores
  `TELA:`).

**Processamento:**
- Remap das palavras para o tempo do corte final (funções existentes de
  `src/compose.py`).
- Mescla com a copy via `merge_corrected_text`: palavras reais do corte,
  grafia da copy. Trecho falado sem correspondência na copy fica como o ASR
  ouviu (melhor esforço) e entra no relatório de divergência.
- Marcadores `TELA:` da copy são reancorados no bloco onde aquele trecho foi
  realmente falado (âncora por similaridade de tokens, mesma normalização de
  `normalize_text`).
- Bloco = segmento mantido do corte; bloco com menos de 1,5s é fundido com o
  seguinte (duração mínima de leitura — jump cuts do preset seco geram
  segmentos curtos demais para virarem unidade de cena). Quem decide CENA
  continua sendo a skill `transcript-to-motion` (3–8 cenas), agora cortando
  apenas em fronteiras de bloco.

**Saída — `output/handoff_<slug>.md`** (contrato novo, versionado no
cabeçalho):

```markdown
# Handoff — <slug>  (v1)
Fonte: corte aprovado (EditorClaude) · Corte: 43.2s · Blocos: 12
Copy: [[02 Áreas/Conteúdo/<nota>]]

## Blocos
0:00.0 → 0:01.6  Eu não entro mais em call de cliente sem isso
TELA: **MEETILY**
0:01.6 → 0:10.5  Terminei a call, abri e o resumo já estava pronto
...

## Divergências (revisar se necessário)
- bloco 7: sem correspondência na copy ("aí eu fui e testei na hora")
```

Formato deliberadamente igual ao "copy timestamped" que a skill
`transcript-to-motion` já detecta — com tempos reais do corte final.

### 2. Skill `transcript-to-motion` (ajuste pequeno, MotionSkills)

Nova fonte `handoff`, detectada pelo cabeçalho `Fonte: corte aprovado`:
- Tempos são exatos: sem estimativa de 150wpm, sem margem de +20%.
  Master = duração exata do corte; cenas com duração exata dos blocos.
- Fronteira de cena só em fronteira de bloco.
- `brief.md` registra `Fonte: handoff (corte aprovado <slug>)`.
- Todo o resto da skill (mapeamento trecho→skill, retenção, split-safe,
  brand logos) intocado.

### 3. `prepare_compose.py` — sem mudança

O fuzzy matching de âncoras continua como está: é o que dá robustez a
re-corte ("re-cortou? roda de novo e os offsets se atualizam"). A causa real
de erro de casamento — texto do brief vindo da copy divergente — desaparece,
porque o brief passa a nascer do texto real. Âncora exata por timestamp seria
otimização prematura (decisão explícita do brainstorm).

### 3b. `compose_premiere.py --somente-corte` vira independente do manifest

Hoje o modo corte exige o manifest e a existência de TODOS os clips (o 1º
motion entra como molde de formato da sequência 1080x1920 @30). No fluxo novo
a ETAPA CORTE acontece antes de existir clip renderizado — o argumento
`manifest` passa a ser opcional no modo `--somente-corte`, e o formato da
sequência vem dos defaults de layout (mesmos valores que o `prepare_compose`
grava: 1080x1920 @30, definidos no style). Fora do modo corte, nada muda.

### 4. Integração com o vault (convenção, sem código novo no vault)

**Leitura:** a copy canônica é uma nota do vault (área Conteúdo). Ao entrar no
pipeline, o frontmatter da nota ganha `slug` e `status: entregue-ao-pipeline`
— campos que o template `98 Templates/Ideia de Conteúdo.md` já prevê.

**Escrita:** ao fechar o QA de legendas, o agente do EditorClaude grava a nota
de resultado no vault seguindo os templates de `98 Templates/` e a
`99 Contexto/arquitetura-do-vault.md` — nunca inventa estrutura nova. A nota
linka `[[copy]]`, transcript real do corte (texto corrido), brief e caminhos
dos artefatos locais.

**Fora do pipeline:** melhoria automática e grafo (o vault já roda sozinho);
métricas (EstudoConteudo/Supabase — número não entra em nota, regra do
template).

### 5. Orquestração Maestri

- Terminal `Produtor de Video` no canvas do MotionSkills (role já existe),
  **desselecionado** — selecionado, o Maestri para de monitorar e a resposta
  não volta.
- O Maestro envia: caminho do handoff + relatório de divergência. Envio é
  automático mesmo com divergência alta (o relatório avisa, não bloqueia —
  decisão explícita do brainstorm).
- `maestri notify` quando os clips renderizarem.
- A sequência do passo 3b da skill `rough-cut` ganha um item novo entre o
  checkpoint de corte (item 4) e a ETAPA MOTIONS (item 5): "gerar handoff →
  enviar ao MotionSkills → seguir para a ETAPA MOTIONS quando os clips
  chegarem". Consequência documentada: o `prepare_compose` (item 1 do 3b)
  passa a rodar DEPOIS da chegada dos clips, não antes do corte.

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| Copy não encontrada no vault | Handoff sai só do transcript, com aviso destacado pedindo revisão humana do texto (grafia de marca pode estar errada) antes do envio. |
| Divergência alta (muito improviso) | Blocos sem correspondência marcados na seção Divergências; envio continua automático, relatório vai junto. |
| Premiere fechado / timeline ilegível | Fallback para cutlist, com aviso de que o handoff reflete o corte automático, não o ajuste manual. |
| Re-corte depois do handoff | Fuzzy matching do compose absorve (comportamento atual). Mudança grande: regenerar handoff e pedir ajuste de cenas ao produtor. |
| Render de clip falha no MotionSkills | Regra atual: renderiza os demais, reporta no fim. |

## Testes

- `tests/test_handoff.py` standalone (padrão do repo, sem pytest): transcript
  sintético + cutlist + copy fake → valida merge, reancoragem de `TELA:`,
  agrupamento de blocos curtos, formato e tempos.
- Golden com dados reais: `transcript_meetily.json` + `cutlist_meetily.json`
  de `output/` → blocos do handoff devem ser compatíveis com o
  `motion_manifest_meetily.json` que funcionou em produção.
- Sanidade MotionSkills (manual, uma vez): handoff do meetily → brief gerado
  comparado com o brief existente.

## Fora de escopo

- Motor de melhoria / grafo do vault (já operacional, projeto próprio).
- Métricas de conteúdo (EstudoConteudo/Supabase).
- Mudanças nas etapas de cor e legendas do rough-cut.
- Legendas karaokê (backlog separado).
- Âncoras exatas por timestamp no `prepare_compose` (revisitar só se o fuzzy
  falhar com briefs nascidos de handoff — hipótese: não falha).
