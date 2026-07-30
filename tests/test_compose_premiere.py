"""Testes do composer Premiere (transform da câmera e JSX de Motion).

Rodar: .venv/bin/python tests/test_compose_premiere.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters" / "premiere_mcp"))

from compose_premiere import build_motion_jsx, camera_transform


def test_camera_transform_4k_to_bottom_half():
    scale, pos = camera_transform(src_w=3840, src_h=2160,
                                  seq_w=1080, seq_h=1920)
    # 2160 -> 960 de altura = 44.44%; centro da metade de baixo = (0.5, 0.75)
    assert abs(scale - 44.44) < 0.01, scale
    assert pos == [0.5, 0.75], pos


def test_motion_jsx_sets_scale_and_position_on_track():
    jsx = build_motion_jsx(track_index=1, scale=44.44, position=[0.5, 0.75])
    assert '"Motion"' in jsx
    assert 'displayName === "Scale"' in jsx and "setValue(44.44, true)" in jsx
    assert 'displayName === "Position"' in jsx and "setValue([0.5, 0.75], true)" in jsx
    assert "videoTracks[1]" in jsx and "JSON.stringify" in jsx


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
