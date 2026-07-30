"""Testes do composer Premiere (transform da câmera e JSX de Motion).

Rodar: .venv/bin/python tests/test_compose_premiere.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters" / "premiere_mcp"))

from compose_premiere import (build_crop_jsx, build_motion_jsx,
                              build_music_place_jsx, camera_transform)


def test_camera_transform_4k_standard_framing():
    scale, pos, crop_top = camera_transform(src_w=3840, src_h=2160,
                                            seq_w=1080, seq_h=1920)
    # enquadramento padrão (validado ao vivo 2026-07-30 na reel_plugin_admin):
    # zoom 1.305x sobre o fill da metade (44.44 -> 58) com a cabeça quase
    # encostando na divisa; crop top devolve a divisa exata em y=960
    assert abs(scale - 58.0) < 0.01, scale
    assert pos == [0.58, 0.6825], pos
    assert abs(crop_top - 22.03) < 0.01, crop_top


def test_camera_transform_crop_restores_divide():
    # topo visível do clipe = divisa (seq_h/2), sem invadir o motion nem
    # abrir fresta; pé do clipe cobre até o fim do quadro
    seq_h = 1920
    scale, pos, crop_top = camera_transform(3840, 2160, 1080, seq_h)
    clip_h = 2160 * scale / 100
    clip_top = pos[1] * seq_h - clip_h / 2
    visible_top = clip_top + clip_h * crop_top / 100
    assert abs(visible_top - seq_h / 2) < 1, visible_top
    assert clip_top + clip_h >= seq_h, clip_top + clip_h


def test_motion_jsx_sets_scale_and_position_on_track():
    jsx = build_motion_jsx(track_index=1, scale=58.0, position=[0.58, 0.6825])
    assert '"Motion"' in jsx
    assert 'displayName === "Scale"' in jsx and "setValue(58.0, true)" in jsx
    assert 'displayName === "Position"' in jsx and "setValue([0.58, 0.6825], true)" in jsx
    assert "videoTracks[1]" in jsx and "JSON.stringify" in jsx


def test_crop_jsx_sets_top_by_display_name():
    jsx = build_crop_jsx(track_index=1, top_pct=22.03)
    assert '"Crop"' in jsx and "setValue(22.03, true)" in jsx
    assert 'displayName === "Top"' in jsx
    # nunca endereçar componente pela última posição (bug de ordem de
    # inserção do Premiere 26)
    assert "numItems - 1" not in jsx
    assert "videoTracks[1]" in jsx and "JSON.stringify" in jsx


def test_music_place_jsx_uses_overwrite_on_empty_track():
    jsx = build_music_place_jsx("000f9999", track_index=2, offset=20,
                                total=57.5)
    # overwriteClip em track VAZIA — add_to_timeline_batch para áudio apagou
    # a voz do usuário (trackIndex endereça o par vídeo+áudio); nunca de novo
    assert "overwriteClip" in jsx and "audioTracks[2]" in jsx
    assert "add_to_timeline" not in jsx
    assert "não está vazia" in jsx, "precisa recusar track ocupada"
    assert "setInPoint(20, 4)" in jsx and "setOutPoint(77.5, 4)" in jsx


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
