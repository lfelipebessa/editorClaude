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


def strip_markdown(text: str) -> str:
    """Remove frontmatter, comentários, cabeçalhos e ênfases — sobra a fala."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s.*$", " ", text, flags=re.M)
    return re.sub(r"[*_`>|]", " ", text)


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
