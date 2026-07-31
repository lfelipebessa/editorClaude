"""Testes do speedup (aceleração 1.2x padrão do canal) com o fixture real.

Rodar: .venv/bin/python tests/test_speedup.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from speedup import default_output, load_speed_rate, speedup

FFPROBE = "/opt/homebrew/bin/ffprobe"
FIXTURE = Path(__file__).parent / "fixture_gaps.mp4"


def probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = [FFPROBE, "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries,
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_duration_shrinks_by_rate():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "fixture_12x.mp4"
        speedup(FIXTURE, out, rate=1.2)
        orig = float(probe(FIXTURE, "format=duration"))
        sped = float(probe(out, "format=duration"))
        expected = orig / 1.2
        assert abs(sped - expected) < 0.3, f"esperava ~{expected:.2f}s, saiu {sped:.2f}s"
        # áudio precisa continuar existindo (atempo preserva pitch, não remove stream)
        assert probe(out, "stream=codec_type", "a") == "audio"
        # fps não pode cair — aceleração é por setpts, não por descarte de timebase
        fps_in = probe(FIXTURE, "stream=r_frame_rate", "v")
        fps_out = probe(out, "stream=r_frame_rate", "v")
        assert fps_in == fps_out, f"fps mudou: {fps_in} -> {fps_out}"


def test_default_output_name_carries_rate():
    out = default_output(Path("/videos/dji_20260731.mp4"), 1.2)
    assert out == Path("/videos/dji_20260731_12x.mp4"), out
    out = default_output(Path("/videos/take.mov"), 1.5)
    assert out == Path("/videos/take_15x.mp4"), out


def test_style_default_is_12x():
    assert abs(load_speed_rate("seco") - 1.2) < 1e-9


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok {fn.__name__}")
    print(f"{len(fns)} testes passaram")
