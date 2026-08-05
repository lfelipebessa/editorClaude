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
print("test_diff_copy: OK")
