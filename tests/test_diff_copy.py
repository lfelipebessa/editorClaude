"""Roda direto: .venv/bin/python tests/test_diff_copy.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from diff_copy import diff_chunks, render_report, strip_markdown, tokenize

copy = "te mando o passo a passo e o convite pro meu grupo"
falado = "te mando o passo a passo e me segue pra não perder"
chunks = diff_chunks(tokenize(copy), tokenize(falado))
assert len(chunks) == 1 and chunks[0]["tipo"] == "replace"
assert "convite" in chunks[0]["copy"] and "segue" in chunks[0]["falado"]
assert chunks[0]["contexto"].endswith("passo e")

md = "---\ntipo: copy\n---\n# Título\nfala **real** aqui\n<!-- nota -->"
assert tokenize(strip_markdown(md)) == ["fala", "real", "aqui"]

tcut = {"cut_duration": 30.0, "source": {"speed_rate": 1.2}, "words": []}
report = render_report(chunks, tokenize(copy), tcut, "teste")
assert "36.0s" in report                      # 30.0 × 1.2 = ritmo natural
assert "12 palavras" in report                # a copy do teste
assert "sinal de ritmo" not in report         # 36s natural > ~4.8s da copy:
                                              # alerta só quando falou RÁPIDO
# caso "falou rápido": copy longa (60 tokens ~24s) e fala natural de 12s
copy_longa = ["palavra"] * 60
tcut_rapido = {"cut_duration": 10.0, "source": {"speed_rate": 1.2}, "words": []}
report2 = render_report([], copy_longa, tcut_rapido, "x")
assert "sinal de ritmo" in report2

# nota real de copy publicada: frontmatter + preâmbulo (Tema/Âncora) fora da
# seção "## Copy integral" + blocos com cabeçalho de timestamp em negrito +
# FALA (com wikilink) + TELA/VISUAL (nunca ditas) + postscript depois de outro
# heading de mesmo nível ("## Notas de leitura") — só a fala deve sobrar.
nota_real = (
    "---\n"
    "tipo: copy-publicada\n"
    "rascunho: true\n"
    "---\n"
    "\n"
    "<!-- comentário de revisão, não é fala -->\n"
    "\n"
    "# Título da copy\n"
    "\n"
    "**Tema:** assunto de teste. **Âncora:** ideia de teste. ~10s.\n"
    "\n"
    "## Copy integral\n"
    "\n"
    "**[0:00-0:06] GANCHO**\n"
    "- FALA: primeira frase [[Alvo|Apelido]]\n"
    "- TELA: TEXTO NA TELA\n"
    "- VISUAL: descrição da cena\n"
    "\n"
    "**[0:06-0:10] BLOCO**\n"
    "- FALA: segunda frase aqui\n"
    "\n"
    "## Notas de leitura\n"
    "\n"
    "Isso aqui é comentário de revisão pós-gravação, não é falado.\n"
)
tokens_real = tokenize(strip_markdown(nota_real))
assert tokens_real == ["primeira", "frase", "alvo", "segunda", "frase", "aqui"], tokens_real
assert "apelido" not in tokens_real
for palavra_proibida in ("tela", "visual", "gancho", "tema", "bloco",
                         "isso", "comentario", "ancora"):
    assert palavra_proibida not in tokens_real, palavra_proibida

# nota real do vault (read-only, zero-noise harness): extrai só as linhas
# FALA e confere que casar essa fala consigo mesma (como se fosse o
# transcript_cut) não gera NENHUMA divergência.
vault_note = Path(
    "/Users/luizfelipebessa/development/2Cerebro/03 Recursos/Swipe/"
    "Minhas copies/5 plugins Claude Code.md")
if vault_note.exists():
    real_copy_tokens = tokenize(strip_markdown(vault_note.read_text()))
    assert real_copy_tokens, "nota real não rendeu nenhum token de fala"
    fake_tcut_words = [{"word": t} for t in real_copy_tokens]
    real_spoken_tokens = tokenize(" ".join(w["word"] for w in fake_tcut_words))
    real_chunks = diff_chunks(real_copy_tokens, real_spoken_tokens)
    assert real_chunks == [], real_chunks

print("test_diff_copy: OK")
