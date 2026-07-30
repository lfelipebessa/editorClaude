"""Testes das heurísticas do cutlist com transcript sintético.

Rodar: .venv/bin/python tests/test_cutlist.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cutlist import generate_cutlist


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
