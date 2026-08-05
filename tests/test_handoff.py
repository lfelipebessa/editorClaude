"""Testes do núcleo do handoff de motions (motion_handoff.py).

Rodar: .venv/bin/python tests/test_handoff.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from motion_handoff import merge_with_copy, parse_copy


def W(word, start, end, clip=0):
    return {"word": word, "start": start, "end": end, "clip": clip}


def test_merge_grafia_vem_da_copy():
    words = [W("cloud", 0.0, 0.4), W("code", 0.5, 0.9), W("resolve", 1.0, 1.5)]
    copy = [{"text": "Claude Code resolve"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["Claude", "Code", "resolve"], out
    assert out[0]["start"] == 0.0 and out[1]["end"] == 0.9, "timing é do falado"
    assert all(w["matched"] for w in out), out


def test_merge_improviso_fica_como_asr():
    words = [W("isso", 0.0, 0.3), W("aqui", 0.4, 0.7), W("é", 0.8, 0.9),
             W("surreal", 1.0, 1.5), W("demais", 1.6, 2.0)]
    copy = [{"text": "isso aqui"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["isso", "aqui", "é", "surreal",
                                       "demais"], out
    assert [w["matched"] for w in out] == [True, True, False, False, False]


def test_merge_copy_nao_falada_nao_entra():
    words = [W("comenta", 0.0, 0.4), W("reunião", 0.5, 1.0)]
    copy = [{"text": "comenta reunião que eu te mando o link"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["comenta", "reunião"], out


def test_merge_sem_copy_marca_tudo_nao_casado():
    words = [W("oi", 0.0, 0.3)]
    out = merge_with_copy(words, [])
    assert out[0]["word"] == "oi" and out[0]["matched"] is False


def test_parse_copy_ignora_frontmatter_heading_timestamp():
    md = ("---\ntipo: ideia\nstatus: trabalhada\n---\n"
          "# Gancho\n"
          "0:00 → 0:07 Eu não entro mais em call sem isso\n"
          "TELA: **MEETILY**\n"
          "[00:19] Roda tudo local\n")
    chunks, telas = parse_copy(md)
    text = chunks[0]["text"]
    assert "Eu não entro mais em call sem isso" in text, text
    assert "Roda tudo local" in text, text
    assert "0:00" not in text and "00:19" not in text, text
    assert "MEETILY" not in text, "TELA não é prosa"
    assert len(telas) == 1 and telas[0]["text"] == "**MEETILY**", telas
    assert telas[0]["anchor"] == ["mais", "em", "call", "sem", "isso"], telas


def test_parse_copy_vazia():
    chunks, telas = parse_copy("---\ntipo: ideia\n---\n")
    assert chunks == [] and telas == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} testes passaram")
