"""Testes de cut_artifacts — roda direto: .venv/bin/python tests/test_cut_artifacts.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cut_artifacts import (cut_to_src, infer_speed_rate, offset_table,
                           remap_silences, remap_words_rich,
                           segments_from_clips, segments_from_cutlist,
                           write_cut_artifacts)

# --- sintético ---
assert offset_table([]) == []

segs = [{"src_start": 10.0, "src_end": 12.0}, {"src_start": 20.0, "src_end": 21.0}]
table = offset_table(segs)
assert table == [
    {"cut_start": 0.0, "cut_end": 2.0, "src_start": 10.0, "src_end": 12.0},
    {"cut_start": 2.0, "cut_end": 3.0, "src_start": 20.0, "src_end": 21.0}]
assert cut_to_src(0.5, table) == 10.5
assert cut_to_src(2.5, table) == 20.5
try:
    cut_to_src(9.9, table)
    assert False, "devia lançar ValueError fora do corte"
except ValueError:
    pass

words = [{"word": "Oi", "start": 10.1, "end": 10.4, "score": 0.9},
         {"word": "sumida", "start": 15.0, "end": 15.5, "score": 0.8},
         {"word": "tchau", "start": 20.2, "end": 20.6, "score": 0.7}]
rich = remap_words_rich(words, table)
assert [w["word"] for w in rich] == ["Oi", "tchau"]  # "sumida" foi cortada
assert rich[0]["score"] == 0.9 and rich[0]["src_start"] == 10.1
assert rich[1]["clip"] == 1 and rich[1]["start"] == 2.2

sil = remap_silences([{"start": 11.0, "end": 13.0}], table)
assert sil == [{"start": 1.0, "end": 2.0}]  # interseção com o trecho mantido

clips = [{"start": 5.0, "inPoint": 20.0, "outPoint": 21.0, "end": 6.0},
         {"start": 0.0, "inPoint": 10.0, "outPoint": 12.0, "end": 2.0}]
assert segments_from_clips(clips) == segs  # ordena pela timeline

assert infer_speed_rate({"source": {"path": "/x/video_12x.mp4"}}, 1.2) == 1.2
assert infer_speed_rate({"source": {"path": "/x/video.mp4"}}, 1.2) == 1.0

# --- words= override: transcript_cut carrega o texto CORRIGIDO (SRT), não o
# extraído bruto do transcript (bug real: cloud->Claude sobrevivia sem isso) ---
transcript_synth = {
    "source": {"path": "/x/video.mp4"},
    "segments": [{"words": [
        {"word": "cloud", "start": 10.1, "end": 10.4, "score": 0.9},
        {"word": "tchau", "start": 20.2, "end": 20.6, "score": 0.7}]}]}
corrected_words = [
    {"word": "Claude", "start": 10.1, "end": 10.4, "score": 0.9},
    {"word": "tchau", "start": 20.2, "end": 20.6, "score": 0.7}]
with tempfile.TemporaryDirectory() as td:
    _, p_tr = write_cut_artifacts(transcript_synth, segs, "timeline", "synth",
                                  1.0, Path(td), words=corrected_words)
    tcut = json.loads(p_tr.read_text())
    got = [w["word"] for w in tcut["words"]]
    assert got == ["Claude", "tchau"], got  # texto corrigido, não "cloud"
    assert tcut["words"][0]["score"] == 0.9, tcut["words"][0]  # score preservado

# --- dados reais: os DOIS footages (dji_12x e meetily — requisito da spec) ---
root = Path(__file__).resolve().parent.parent
for tr_name, cl_name, rate in [("transcript_dji_12x", "cutlist_dji_12x", 1.2),
                               ("transcript_meetily", "cutlist_meetily", 1.0)]:
    transcript = json.loads((root / f"output/{tr_name}.json").read_text())
    cutlist = json.loads((root / f"output/{cl_name}.json").read_text())
    with tempfile.TemporaryDirectory() as td:
        p_cut, p_tr = write_cut_artifacts(
            transcript, segments_from_cutlist(cutlist), "cutlist",
            tr_name.replace("transcript_", ""), rate, Path(td))
        tcut = json.loads(p_tr.read_text())
        assert tcut["origem"] == "cutlist"
        assert tcut["source"]["speed_rate"] == rate
        kept = round(sum(s["end"] - s["start"] for s in cutlist["segments"]), 3)
        assert abs(tcut["cut_duration"] - kept) < 0.01, tr_name
        assert tcut["words"] and all("score" in w for w in tcut["words"])
        assert tcut["offsets"], tr_name
        final = json.loads(p_cut.read_text())
        assert ([s["start"] for s in final["segments"]]
                == [s["start"] for s in cutlist["segments"]])
print("test_cut_artifacts: OK")
