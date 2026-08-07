"""Diff copy aprovada × fala real do corte — TRAVA do checkpoint 2 (pré-publicação).

Compara o texto da copy (arquivo .md/.txt — a copy canônica é a nota de
conteúdo do vault) com as palavras do transcript_cut.json. Reporta as
divergências com contexto + durações (publicada e em ritmo natural, usando
source.speed_rate — sem essa correção todo vídeo 1.2x pareceria "falado
rápido"). O operador julga CTA, fosso e keyword ANTES de publicar.

FRONTEIRA: nunca escreve no vault, nunca lê métrica. Relatório em
output/diff_copy_<slug>.md; a conclusão qualitativa vai pro vault pela mão do
operador (seção datada em 'O vídeo gravado não é o roteiro aprovado').

Uso:
    python src/diff_copy.py <copy.md> output/transcript_cut_<slug>.json
"""
import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose import normalize_text


def tokenize(text: str) -> list[str]:
    return normalize_text(text).split()


FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HEADING_RE = re.compile(r"^#{1,6}\s")
COPY_INTEGRAL_RE = re.compile(r"^(#{1,6})\s*copy integral\b", re.I)
# marcador FALA — o único conteúdo realmente dito. Variantes: "- FALA:",
# "**FALA:**", case-insensitive.
FALA_RE = re.compile(r"^-?\s*\**\s*fala\s*:\s*\**\s*(.*)$", re.I)
# TELA/VISUAL/POR QUÊ são direção de cena e justificativa — nunca foram
# ditas em voz alta, somem inteiras (mesma fronteira do motion_handoff.TELA_RE).
DROP_MARKER_RE = re.compile(r"^-?\s*\**\s*(tela|visual|por qu[eê])\s*:", re.I)
# preâmbulo de planejamento da nota (Tema/Âncora/Formato) — antes da seção
# "Copy integral" na prática, mas dropado aqui também como cinto e suspensório.
PREAMBLE_RE = re.compile(r"^-?\s*\**\s*(tema|âncora|ancora|formato)\s*:", re.I)
# cabeçalho de bloco em negrito: "**[0:00-0:06] GANCHO**"
TS_HEADER_RE = re.compile(
    r"^\*\*\[\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*\]\s*.*?\*\*\s*$")
# mesma convenção de motion_handoff.WIKILINK_RE: [[Alvo|Apelido]] -> Alvo
# (não importa de lá — módulo irmão, com seus próprios gaps; ver spec).
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
# rubrica entre colchetes — prefixo de timestamp ("[00:00]", "[0:00 — hook,
# dor-sintoma]") ou aside inline ("[mostra a tela]"): nunca foi dito, some
# inteira (span + conteúdo). Roda DEPOIS do wikilink resolver (que usa
# colchete duplo e já colapsou pro Alvo) — senão comeria o wikilink também.
BRACKET_RE = re.compile(r"\[[^\]]*\]")
# rubrica entre parênteses ("(atrás: grid de UIs genéricas...)") — mesma
# lógica: direção de cena/produção, não fala. Nas notas reais examinadas a
# fala nunca depende de parênteses; se aparecer um caso real onde a fala
# mora entre parênteses, isso vira um TODO revisado à parte.
PAREN_RE = re.compile(r"\([^)]*\)")


def _copy_integral_section(text: str) -> str:
    """Isola a seção '## Copy integral' (até o próximo heading de nível
    igual ou maior). Sem essa seção, usa o corpo inteiro — fallback para
    notas de prosa pura (ex.: 'Skill de SEO') que não têm essa estrutura."""
    lines = text.splitlines()
    start = level = None
    for i, line in enumerate(lines):
        m = COPY_INTEGRAL_RE.match(line.strip())
        if m:
            start, level = i + 1, len(m.group(1))
            break
    if start is None:
        return text
    end = len(lines)
    for j in range(start, len(lines)):
        hm = re.match(r"^(#{1,6})\s", lines[j].strip())
        if hm and len(hm.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def strip_markdown(text: str) -> str:
    """Extrai só a fala real da nota de copy do vault — não o roteiro
    inteiro (que carrega TELA, VISUAL, timestamps e notas de planejamento
    que nunca foram ditas em voz alta).

    Ordem:
    1. Isola '## Copy integral' se existir (senão usa a nota inteira).
    2. Remove frontmatter e comentários HTML.
    3. Linha por linha: 'FALA:' vira conteúdo mantido; 'TELA:'/'VISUAL:'/
       'POR QUÊ:' (direção de cena) somem; preâmbulo ('**Tema:**' etc.) e
       cabeçalho de bloco ('**[0:00-0:06] GANCHO**') somem; heading markdown
       some.
    4. Sem nenhuma linha FALA: na nota, cai no fallback: mantém as linhas de
       prosa que sobraram do passo 3 (comportamento antigo, para notas sem
       essa estrutura de roteiro) — MAS o fallback também é roteiro, não
       transcrição: prefixo de timestamp em colchetes e aside entre
       colchetes/parênteses são tão rubrica quanto TELA/VISUAL, então os
       passos 5b/5c abaixo valem para os dois caminhos, não só pra FALA.
    5. Wikilink [[Alvo|Apelido]] -> Alvo; DEPOIS disso, qualquer colchete
       [...] restante (rubrica) e parêntese (...) (rubrica) somem inteiros,
       em qualquer um dos dois caminhos (FALA ou fallback).
    6. Ênfase markdown (*_`>|) é removida por último.
    """
    text = FRONTMATTER_RE.sub("", text)
    text = COMMENT_RE.sub(" ", text)
    body = _copy_integral_section(text)

    fala_lines, prose_lines, found_fala = [], [], False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if TS_HEADER_RE.match(line):
            continue
        if DROP_MARKER_RE.match(line):
            continue
        if PREAMBLE_RE.match(line):
            continue
        m = FALA_RE.match(line)
        if m:
            found_fala = True
            fala_lines.append(m.group(1))
            continue
        if HEADING_RE.match(line):
            continue
        prose_lines.append(line)

    kept = "\n".join(fala_lines if found_fala else prose_lines)
    kept = WIKILINK_RE.sub(r"\1", kept)
    kept = BRACKET_RE.sub(" ", kept)
    kept = PAREN_RE.sub(" ", kept)
    return re.sub(r"[*_`>|]", " ", kept)


def diff_chunks(copy_tokens: list[str], spoken_tokens: list[str],
                context: int = 4) -> list[dict]:
    matcher = SequenceMatcher(None, copy_tokens, spoken_tokens, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        out.append({"tipo": tag,
                    "copy": " ".join(copy_tokens[i1:i2]),
                    "falado": " ".join(spoken_tokens[j1:j2]),
                    "contexto": " ".join(copy_tokens[max(0, i1 - context):i1])})
    return out


def render_report(chunks: list[dict], copy_tokens: list[str],
                  tcut: dict, slug: str) -> str:
    rate = tcut["source"].get("speed_rate", 1.0)
    cut_dur = tcut["cut_duration"]
    natural = round(cut_dur * rate, 1)
    copy_est = round(len(copy_tokens) / 2.5, 1)  # 150 palavras/min PT-BR
    lines = [f"# Diff copy × fala — {slug}", "",
             f"- duração publicada (corte): {cut_dur}s",
             f"- fala em ritmo natural (×{rate}): {natural}s",
             f"- copy: {len(copy_tokens)} palavras (~{copy_est}s a 150 ppm)", ""]
    if copy_est and natural < copy_est * 0.85:
        lines += ["⚠️ fala natural bem mais curta que a copy — sinal de ritmo "
                  "acelerado na gravação (ritmo é retenção; ver 'O vídeo "
                  "gravado não é o roteiro aprovado')", ""]
    if not chunks:
        lines.append("Nenhuma divergência de texto entre copy e fala. ✅")
    else:
        lines += [f"## {len(chunks)} divergências — revisar CTA, fosso e keyword", "",
                  "| contexto (copy) | na copy | falado |", "|---|---|---|"]
        for c in chunks:
            lines.append(f"| …{c['contexto']} | {c['copy'] or '—'} "
                         f"| {c['falado'] or '—'} |")
    lines += ["", "TRAVA: divergência em CTA ou fosso = corrigir ANTES de "
              "publicar (regravar trecho ou aceitar por escrito).",
              "Pós-publicação: conclusão qualitativa vira seção datada na nota "
              "'O vídeo gravado não é o roteiro aprovado' do vault. "
              "Métrica NUNCA vai pro vault."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("copy", type=Path,
                        help="arquivo .md/.txt da copy aprovada (nota do vault)")
    parser.add_argument("transcript_cut", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()
    for p in (args.copy, args.transcript_cut):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")
    tcut = json.loads(args.transcript_cut.read_text())
    slug = args.transcript_cut.stem.replace("transcript_cut_", "")
    copy_tokens = tokenize(strip_markdown(args.copy.read_text()))
    spoken_tokens = tokenize(" ".join(w["word"] for w in tcut["words"]))
    chunks = diff_chunks(copy_tokens, spoken_tokens)
    report = render_report(chunks, copy_tokens, tcut, slug)
    out = args.out or Path(f"output/diff_copy_{slug}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    print(f"\nrelatório: {out}")


if __name__ == "__main__":
    main()
