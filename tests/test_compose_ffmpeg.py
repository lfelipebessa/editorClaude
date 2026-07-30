"""Testes do composer ffmpeg (montagem do filter graph vertical).

Rodar: .venv/bin/python tests/test_compose_ffmpeg.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from compose_ffmpeg import (build_camera_branch, build_caption_overlays,
                            build_mg_track)

SCENES = [
    {"clip": "/mg/01.mp4", "start": 0.0, "loop": False},
    {"clip": "/mg/02.mp4", "start": 5.4, "loop": True},
]


def test_mg_track_trims_holds_and_concats():
    graph, input_flags = build_mg_track(SCENES, total=10.0, fps=30)
    # cena 1 dura 5.4s; cena 2 dura 4.6s (até o total)
    assert "trim=duration=5.4" in graph and "trim=duration=4.6" in graph
    # hold-safe: clipe curto congela o último frame em vez de dessincronizar
    assert "tpad=stop_mode=clone" in graph
    # corta a metade de CIMA do motion (conteúdo split-safe mora em y 90-910)
    assert "crop=1080:960:0:0" in graph
    assert "concat=n=2:v=1:a=0[mg]" in graph
    # cena com loop entra com -stream_loop -1 nos input flags
    assert input_flags[0] == [] and input_flags[1] == ["-stream_loop", "-1"]


def test_camera_branch_crops_9_8_and_scales():
    branch = build_camera_branch(src_w=3840, src_h=2160, x_offset=0,
                                 color_chain="eq=saturation=1.1", fps=30)
    assert branch.startswith("eq=saturation=1.1,"), branch
    assert "crop=2430:2160:705:0" in branch, branch      # (3840-2430)/2 = 705
    assert "scale=1080:960" in branch and "fps=30" in branch


def test_camera_branch_without_color():
    branch = build_camera_branch(3840, 2160, x_offset=100, color_chain="", fps=30)
    assert branch.startswith("crop=2430:2160:805:0"), branch


def test_caption_overlays_use_time_windows_at_seam():
    chunks = [{"text": "oi", "start": 0.0, "end": 0.5},
              {"text": "tchau", "start": 0.6, "end": 1.2}]
    graph, label = build_caption_overlays(chunks, first_idx=7)
    # cada legenda é um input de imagem sobreposto só na sua janela de tempo
    assert "[7:v]" in graph and "[8:v]" in graph
    assert "enable=between(t\\,0.0\\,0.5)" in graph, graph
    assert "enable=between(t\\,0.6\\,1.2)" in graph
    # apoiada na divisa: borda inferior do PNG em y=976, texto sobre o fundo
    # escuro do motion (mais legível que cavalgar a emenda das metades)
    assert "overlay=(W-w)/2:976-h" in graph
    assert label == "[cap1]" and graph.rstrip().endswith("[cap1]"), (graph, label)


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
