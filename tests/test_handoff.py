"""Testes do núcleo do handoff de motions (motion_handoff.py).

Rodar: .venv/bin/python tests/test_handoff.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from motion_handoff import (_fmt_time, anchor_telas, assign_words,
                            build_blocks, format_handoff, merge_with_copy,
                            parse_copy)


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


def test_merge_palavra_nao_falada_nunca_entra_mesmo_em_replace():
    # regressão: "eu" da copy não pode substituir "terminei"/"a"/"call" só
    # porque o alinhamento global jogou os dois lados no mesmo opcode.
    words = [W("terminei", 0.0, 0.4), W("a", 0.5, 0.6), W("call", 0.7, 1.0)]
    copy = [{"text": "eu"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["terminei", "a", "call"], out
    assert [w["matched"] for w in out] == [False, False, False], out


def test_merge_marca_partida_colapsa_com_timing_do_span():
    words = [W("chat", 0.0, 0.4), W("gpt", 0.4, 0.9)]
    copy = [{"text": "ChatGPT"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["ChatGPT"], out
    assert out[0]["matched"] is True
    assert out[0]["start"] == 0.0 and out[0]["end"] == 0.9, out


def test_merge_grafia_parecida_continua_corrigindo():
    words = [W("cloud", 0.0, 0.4)]
    copy = [{"text": "Claude"}]
    out = merge_with_copy(words, copy)
    assert [w["word"] for w in out] == ["Claude"], out
    assert out[0]["matched"] is True


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


def test_parse_copy_tela_variantes():
    md = ("**TELA:** MEETILY\n"
          "isso aqui\n"
          "- TELA: OUTRA\n"
          "tela: TERCEIRA\n"
          "> TELA: QUARTA\n"
          "**TELA**: QUINTA\n")
    chunks, telas = parse_copy(md)
    assert [t["text"] for t in telas] == ["MEETILY", "OUTRA", "TERCEIRA",
                                          "QUARTA", "QUINTA"], telas
    assert "TELA" not in chunks[0]["text"], chunks
    assert "MEETILY" not in chunks[0]["text"], chunks


def test_parse_copy_limpa_markdown_da_prosa():
    md = "o **Meetily** roda\nuso o [[Claude Code]] direto\n"
    chunks, telas = parse_copy(md)
    text = chunks[0]["text"]
    assert "**" not in text and "[[" not in text and "]]" not in text, text
    assert text.split() == ["o", "Meetily", "roda", "uso", "o", "Claude",
                            "Code", "direto"], text


def test_build_blocks_funde_curto_com_seguinte():
    bounds = [(0.0, 1.0), (1.0, 3.0), (3.0, 3.8)]
    blocks = build_blocks(bounds, min_dur=1.5)
    # (0,1.0) é curto -> funde com o seguinte; sobra final curta -> anterior
    assert [(b["start"], b["end"]) for b in blocks] == [(0.0, 3.8)], blocks


def test_build_blocks_sem_fusao():
    bounds = [(0.0, 2.0), (2.0, 5.5)]
    blocks = build_blocks(bounds, min_dur=1.5)
    assert [(b["start"], b["end"]) for b in blocks] == [(0.0, 2.0),
                                                        (2.0, 5.5)], blocks


def test_assign_words_pertence_pelo_inicio():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("a", 0.1, 0.4), W("b", 1.9, 2.3), W("c", 2.5, 3.0)]
    assign_words(blocks, words)
    assert [w["word"] for w in blocks[0]["words"]] == ["a", "b"]
    assert [w["word"] for w in blocks[1]["words"]] == ["c"]


def test_anchor_tela_cai_no_bloco_do_trecho():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("call", 0.2, 0.5), W("sem", 0.6, 0.8), W("isso", 0.9, 1.2),
             W("roda", 2.1, 2.4), W("tudo", 2.5, 2.8), W("local", 2.9, 3.3)]
    telas = [{"text": "**MEETILY**", "anchor": ["roda", "tudo", "local"]}]
    anchor_telas(telas, words, blocks)
    assert blocks[1].get("telas") == ["**MEETILY**"], blocks
    assert "telas" not in blocks[0]


def test_anchor_tela_sem_ancora_vai_pro_primeiro_bloco():
    blocks = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    words = [W("oi", 0.1, 0.3)]
    telas = [{"text": "**ABRE**", "anchor": []}]
    anchor_telas(telas, words, blocks)
    assert blocks[0].get("telas") == ["**ABRE**"]


def test_format_handoff_cabecalho_blocos_divergencia():
    blocks = [{"start": 0.0, "end": 2.0,
               "words": [{**W("Claude", 0.1, 0.5), "matched": True},
                         {**W("Code", 0.6, 1.0), "matched": True}],
               "telas": ["**MEETILY**"]},
              {"start": 2.0, "end": 4.0,
               "words": [{**W("improviso", 2.1, 2.6), "matched": False},
                         {**W("total", 2.7, 3.2), "matched": False}]}]
    md = format_handoff("meetily", blocks, "Copy Meetily")
    assert md.startswith("# Handoff — meetily  (v1)\n"), md
    assert "Fonte: corte aprovado (EditorClaude) · Corte: 4.0s · Blocos: 2" in md
    assert "Copy: [[Copy Meetily]]" in md
    assert "0:00.0 → 0:02.0  Claude Code" in md, md
    assert "TELA: **MEETILY**" in md
    assert "## Divergências" in md and "bloco 2" in md, md


def test_format_handoff_sem_copy_avisa():
    blocks = [{"start": 0.0, "end": 2.0,
               "words": [{**W("oi", 0.1, 0.5), "matched": False}]}]
    md = format_handoff("x", blocks, None)
    assert "Copy: NENHUMA" in md, md


def test_fmt_time_arredonda_antes_de_fatiar():
    assert _fmt_time(59.96) == "1:00.0"
    assert _fmt_time(599.96) == "10:00.0"
    assert _fmt_time(0.0) == "0:00.0"
    assert _fmt_time(125.3) == "2:05.3"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} testes passaram")
