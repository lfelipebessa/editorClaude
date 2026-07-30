"""Testes das heurísticas do cutlist com transcript sintético.

Rodar: .venv/bin/python tests/test_cutlist.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cutlist import generate_cutlist, load_style


def make_transcript(words, duration=None, silences=None):
    """words: lista de (texto, start, end)."""
    duration = duration or (words[-1][2] + 1.0)
    return {
        "source": {"path": "/fake/video.mp4", "duration": duration},
        "language": "pt",
        "silences": silences or [],
        "segments": [{
            "start": words[0][1],
            "end": words[-1][2],
            "text": " ".join(w[0] for w in words),
            "words": [{"word": w[0], "start": w[1], "end": w[2], "score": 0.9}
                      for w in words],
        }],
    }


def reasons(cutlist):
    return {r["reason"] for r in cutlist["removed"]}


def removed_texts(cutlist, reason):
    return [r["text"] for r in cutlist["removed"] if r["reason"] == reason]


def test_long_silence_is_cut():
    t = make_transcript([
        ("olá", 0.5, 0.9),
        ("pessoal", 1.0, 1.5),
        ("voltamos", 5.0, 5.6),   # 3.5s de pausa antes
        ("agora", 5.7, 6.1),
    ])
    c = generate_cutlist(t)
    assert len(c["segments"]) == 2, c["segments"]
    assert "silence" in reasons(c), c["removed"]
    gap = c["segments"][1]["start"] - c["segments"][0]["end"]
    assert gap > 2.0, f"gap mantido de só {gap}s"


def test_stutter_removed_keeps_last():
    t = make_transcript([
        ("eu", 0.5, 0.7),
        ("eu", 0.8, 1.0),
        ("vou", 1.1, 1.4),
        ("mostrar", 1.5, 2.0),
    ])
    c = generate_cutlist(t)
    assert removed_texts(c, "stutter") == ["eu"], c["removed"]


def test_bigram_stutter_removed():
    t = make_transcript([
        ("eu", 0.5, 0.7),
        ("vou", 0.8, 1.0),
        ("eu", 1.1, 1.3),
        ("vou", 1.4, 1.6),
        ("mostrar", 1.7, 2.2),
        ("tudo", 2.3, 2.6),
    ])
    c = generate_cutlist(t)
    assert removed_texts(c, "stutter") == ["eu", "vou"], c["removed"]


def test_false_start_removed():
    t = make_transcript([
        ("hoje", 0.5, 0.8),
        ("vamos", 0.9, 1.2),
        # pausa > MAX_SILENCE: regra de stutter não se aplica, é falso começo
        ("hoje", 3.0, 3.3),
        ("vamos", 3.4, 3.7),
        ("falar", 3.8, 4.1),
        ("de", 4.2, 4.3),
        ("edição", 4.4, 4.9),
    ])
    c = generate_cutlist(t)
    assert set(removed_texts(c, "false_start")) == {"hoje", "vamos"}, c["removed"]
    assert len(c["segments"]) == 1


def test_repeated_phrase_keeps_last_take():
    take = [("essa", 0.0, 0.3), ("ferramenta", 0.4, 0.9), ("é", 1.0, 1.1),
            ("incrível", 1.2, 1.7), ("demais", 1.8, 2.2)]
    retake = [(w, s + 3.0, e + 3.0) for w, s, e in take]
    t = make_transcript(take + retake)
    c = generate_cutlist(t)
    assert "repetition" in reasons(c), c["removed"]
    assert len(c["segments"]) == 1
    assert c["segments"][0]["start"] >= 2.5, "manteve a primeira tomada, não a última"


def test_isolated_filler_removed():
    t = make_transcript([
        ("bom", 0.5, 0.8),
        ("hum", 1.3, 1.7),    # filler isolado por pausas
        ("vamos", 2.2, 2.6),
        ("começar", 2.7, 3.3),
    ])
    c = generate_cutlist(t)
    assert removed_texts(c, "filler") == ["hum"], c["removed"]


def test_detected_silence_overrides_stretched_word():
    # palavra esticada por cima do silêncio (artefato do aligner)
    t = make_transcript([
        ("primeiro", 0.5, 0.9),
        ("quero", 1.0, 4.5),     # esticada: cruza o silêncio 1.2-4.2
        ("mostrar", 4.6, 5.1),
    ], silences=[{"start": 1.2, "end": 4.2}])
    c = generate_cutlist(t)
    assert len(c["segments"]) == 2, c["segments"]
    assert "silence" in reasons(c)


def test_edge_trim_cuts_into_speech():
    # palavras de borda longas (>= min_word_protect) recebem trim integral
    t = make_transcript([
        ("fala", 1.0, 1.45),
        ("normal", 1.5, 1.95),
        ("aqui", 2.0, 2.5),
    ])
    c = generate_cutlist(t, {"trim_start": 0.07, "trim_end": 0.12,
                             "pad_before": 0.0, "pad_after": 0.0})
    seg = c["segments"][0]
    assert abs(seg["start"] - 1.07) < 0.001, seg
    assert abs(seg["end"] - 2.38) < 0.001, seg


def test_edge_trim_never_kills_short_segment():
    t = make_transcript([("oi", 1.0, 1.25)])
    c = generate_cutlist(t, {"trim_start": 0.1, "trim_end": 0.1,
                             "pad_before": 0.0, "pad_after": 0.0})
    seg = c["segments"][0]
    assert seg["end"] - seg["start"] > 0, seg
    assert seg["start"] == 1.0 and seg["end"] == 1.25, "devia manter bordas originais"


def test_max_word_gap_cuts_short_pauses():
    words = [
        ("corta", 0.5, 0.8),
        ("essas", 1.2, 1.5),    # gap 0.4s
        ("pausinhas", 1.9, 2.4),  # gap 0.4s
    ]
    c_default = generate_cutlist(make_transcript(words))
    assert len(c_default["segments"]) == 1, "default não devia cortar gap de 0.4s"
    c_seco = generate_cutlist(make_transcript(words),
                              {"max_word_gap": 0.25, "pad_before": 0.0, "pad_after": 0.0})
    assert len(c_seco["segments"]) == 3, c_seco["segments"]
    assert "silence" in reasons(c_seco)


def test_clean_speech_untouched():
    t = make_transcript([
        ("fala", 0.5, 0.8),
        ("limpa", 0.9, 1.3),
        ("sem", 1.4, 1.6),
        ("erros", 1.7, 2.2),
    ])
    c = generate_cutlist(t)
    assert len(c["segments"]) == 1
    assert not [r for r in c["removed"] if r["reason"] != "silence"], c["removed"]


def test_adaptive_trim_spares_short_word():
    cut = load_style("seco")["cut"]
    t = make_transcript([("oi", 1.0, 1.5)])   # palavra única de 0.5s
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    assert seg["start"] == 1.0 and seg["end"] == 1.5, \
        f"segmento de 0.5s não pode perder nada: {seg}"


def test_adaptive_trim_full_on_long_segment():
    cut = load_style("seco")["cut"]
    words = [(f"palavra{i}", 1.0 + i * 0.5, 1.0 + i * 0.5 + 0.45) for i in range(19)]
    t = make_transcript(words)                # segmento de 1.0 a 10.45 (9.45s)
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    assert abs(seg["start"] - (1.0 + cut["trim_start"])) < 0.001, seg
    assert abs(seg["end"] - (10.45 - cut["trim_end"])) < 0.001, seg


def test_adaptive_trim_capped_by_fraction():
    cut = load_style("seco")["cut"]
    t = make_transcript([("palavra", 1.0, 1.45), ("curta", 1.45, 1.9)])  # 0.9s
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    allowed = cut["trim_max_fraction"] * 0.9
    assert abs(seg["end"] - (1.9 - allowed)) < 0.001, \
        f"trim_end devia ser limitado a {allowed:.3f}s: {seg}"
    assert abs(seg["start"] - (1.0 + cut["trim_start"])) < 0.001, seg


def test_short_last_word_zeroes_trim_end():
    # segmento de 1.2s cuja última palavra tem 0.3s: trim_end zero, palavra intacta
    cut = load_style("seco")["cut"]
    t = make_transcript([
        ("fala", 0.0, 0.5),
        ("rápida", 0.55, 0.9),
        ("já", 0.95, 1.2),
    ])
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    assert seg["end"] == 1.2, f"última palavra curta truncada: {seg}"
    assert abs(seg["start"] - cut["trim_start"]) < 0.001, seg


def test_real_crm_case_last_word_intact():
    # números reais do transcript_dji: 'Organizar o CRM.' + silêncio só em 62.094
    # (aligner fechou 'CRM.' em 61.589, ~0.5s antes da fala acabar)
    cut = load_style("seco")["cut"]
    t = make_transcript([
        ("Organizar", 60.748, 61.188),
        ("o", 61.208, 61.248),
        ("CRM.", 61.308, 61.589),
    ], duration=70.0, silences=[{"start": 62.094, "end": 62.634}])
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    assert seg["end"] >= 61.589, f"'CRM.' truncada: {seg}"
    assert seg["end"] >= 62.0, f"extensão até o silêncio real não aplicada: {seg}"


def test_short_last_word_extension_capped_by_next_segment():
    cut = load_style("seco")["cut"]
    t = make_transcript([
        ("criar", 1.0, 1.45),
        ("já", 1.5, 1.75),          # última palavra curta do 1º segmento
        ("continua", 2.3, 2.9),     # próximo segmento logo depois
        ("falando", 3.0, 3.6),
    ], silences=[{"start": 2.1, "end": 2.25}])
    c = generate_cutlist(t, cut)
    first = c["segments"][0]
    assert first["end"] <= c["segments"][1]["start"], c["segments"]
    assert first["end"] >= 1.75, f"palavra curta truncada: {first}"


def test_style_seco_loads_and_applies():
    style = load_style("seco")
    cut = style["cut"]
    for key in ("trim_start", "trim_end", "trim_min_duration", "trim_max_fraction",
                "trim_max_word_fraction", "min_word_protect", "short_word_end_margin",
                "max_word_gap", "pad_before", "pad_after", "min_segment"):
        assert key in cut, f"styles/seco.json sem '{key}'"
    assert style["language"] == "pt"
    assert set(style["platforms"]) >= {"youtube", "instagram", "tiktok"}

    t = make_transcript([("fala", 1.0, 1.5), ("aqui", 1.6, 2.2)])
    c = generate_cutlist(t, cut)
    seg = c["segments"][0]
    assert abs(seg["start"] - (1.0 + cut["trim_start"])) < 0.001, seg
    assert abs(seg["end"] - (2.2 - cut["trim_end"])) < 0.001, seg
    assert c["settings"]["max_word_gap"] == cut["max_word_gap"]


def test_unknown_style_fails_clearly():
    try:
        load_style("inexistente")
    except SystemExit as e:
        assert "inexistente" in str(e)
    else:
        raise AssertionError("load_style devia falhar para style inexistente")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"ok   {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {test.__name__}: {e}")
    if failed:
        sys.exit(f"{failed}/{len(tests)} testes falharam")
    print(f"{len(tests)} testes passaram")


if __name__ == "__main__":
    main()
