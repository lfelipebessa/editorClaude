"""Testes do núcleo do composer (remap de palavras, legendas, alinhamento de cenas).

Rodar: .venv/bin/python tests/test_compose.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from compose import (find_scene_starts, format_srt, group_captions,
                     normalize_text, parse_srt, remap_words)

WORDS_SRC = [  # tempos no VÍDEO BRUTO
    {"word": "Eu", "start": 1.0, "end": 1.2},
    {"word": "ia", "start": 1.3, "end": 1.5},
    {"word": "contratar", "start": 1.6, "end": 2.1},
    {"word": "um", "start": 5.0, "end": 5.1},      # dentro do 2º segmento
    {"word": "plugin", "start": 5.2, "end": 5.8},
    {"word": "cortado", "start": 3.0, "end": 3.4},  # em região removida
]
CUT_SEGS = [{"start": 0.9, "end": 2.3}, {"start": 4.8, "end": 6.0}]


def test_remap_words_moves_to_output_timeline():
    out = remap_words(WORDS_SRC, CUT_SEGS)
    texts = [w["word"] for w in out]
    assert texts == ["Eu", "ia", "contratar", "um", "plugin"], texts
    assert abs(out[0]["start"] - 0.1) < 1e-6, out[0]      # 1.0 - 0.9
    # 2º segmento começa no output em 1.4 (duração do 1º): 5.0-4.8+1.4 = 1.6
    assert abs(out[3]["start"] - 1.6) < 1e-6, out[3]


def test_remap_drops_words_in_removed_regions():
    out = remap_words(WORDS_SRC, CUT_SEGS)
    assert all(w["word"] != "cortado" for w in out)


def test_group_captions_respects_max_words_and_gap():
    words = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2}
             for i in range(5)]
    words.append({"word": "depois", "start": 4.0, "end": 4.3})  # gap grande
    chunks = group_captions(words, max_words=3, max_gap=0.6)
    assert [c["text"] for c in chunks] == ["w0 w1 w2", "w3 w4", "depois"], chunks
    assert chunks[0]["start"] == 0.0 and chunks[0]["end"] == 0.8


def test_normalize_strips_punctuation_and_case():
    assert normalize_text("Olha, o QUE ele fez!") == "olha o que ele fez"


def test_find_scene_starts_sequential_and_fuzzy():
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.3}
             for i, w in enumerate(
                 "eu ia contratar um funcionário depois olha o que ele fez "
                 "sozinho são trinta tarefas no total".split())]
    scenes = [{"match": "eu ia contratar"},
              {"match": "olha o que ele fez"},
              # 'trinta e uma tarefas' ≠ 'trinta tarefas' — fuzzy tem que achar
              {"match": "são trinta e uma tarefas"}]
    starts = find_scene_starts(scenes, words)
    assert starts[0] == 0.0, starts                    # cena 1 sempre em 0
    assert abs(starts[1] - 3.0) < 1e-6, starts          # "olha" é o índice 6
    assert abs(starts[2] - 6.0) < 1e-6, starts          # "são" é o índice 12
    assert starts == sorted(starts), "cenas devem ser monotônicas"


def test_format_srt():
    chunks = [{"text": "Eu ia contratar", "start": 0.1, "end": 1.4},
              {"text": "um plugin", "start": 1.6, "end": 2.4}]
    srt = format_srt(chunks)
    assert "1\n00:00:00,100 --> 00:00:01,400\nEu ia contratar\n" in srt
    assert "2\n00:00:01,600 --> 00:00:02,400\num plugin\n" in srt


def test_parse_srt_roundtrip():
    chunks = [{"text": "Eu ia contratar", "start": 0.1, "end": 1.4},
              {"text": "um plugin", "start": 1.6, "end": 2.4}]
    parsed = parse_srt(format_srt(chunks))
    assert parsed == chunks, parsed


def test_real_video_alignment_smoke():
    import json
    root = Path(__file__).parent.parent
    transcript = json.loads((root / "output/transcript_dji.json").read_text())
    cutlist = json.loads((root / "output/cutlist_dji_v4.json").read_text())
    words = [w for s in transcript["segments"] for w in s.get("words", [])
             if "start" in w]
    out = remap_words(words, cutlist["segments"])
    total = sum(s["end"] - s["start"] for s in cutlist["segments"])
    assert out and out[-1]["end"] <= total + 0.01
    scenes = [{"match": "eu ia contratar um funcionário"},
              {"match": "olha o que ele fez sozinho"},
              {"match": "são 31 tarefas empacotadas"},
              {"match": "baixa o app do claude"},
              {"match": "eu construo sistema rodando para cliente"},
              {"match": "comenta admin aqui embaixo"}]
    starts = find_scene_starts(scenes, out)
    assert len(starts) == 6 and starts == sorted(starts), starts
    assert starts[0] == 0.0 and starts[-1] < total, starts


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
