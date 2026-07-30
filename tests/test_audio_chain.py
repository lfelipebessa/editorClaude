"""Testes da cadeia de áudio do adaptador ffmpeg (dirigida pelo style file).

Rodar: .venv/bin/python tests/test_audio_chain.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from render_ffmpeg import (build_audio_chain, build_music_chain, load_style,
                           music_gain_db, parse_loudnorm_json,
                           resolve_music_file)

AUDIO_CFG = {
    "target_i": -14.0,
    "target_tp": -1.5,
    "target_lra": 7.0,
    "limiter": {"enabled": True, "limit_db": -1.5, "attack_ms": 5, "release_ms": 100},
}

MEASURED = {
    "input_i": "-23.4", "input_tp": "-4.1", "input_lra": "9.8",
    "input_thresh": "-33.9", "target_offset": "0.3",
}


def test_measure_pass_chain():
    chain = build_audio_chain(AUDIO_CFG, None)
    assert chain == "loudnorm=I=-14.0:TP=-1.5:LRA=7.0:print_format=json", chain


def test_apply_pass_chain_has_measured_linear_and_limiter():
    chain = build_audio_chain(AUDIO_CFG, MEASURED)
    assert "measured_I=-23.4" in chain and "linear=true" in chain, chain
    assert "aresample=48000" in chain, chain
    assert "alimiter=limit=0.8414:attack=5:release=100:level=disabled" in chain, chain
    assert "print_format" not in chain, chain


def test_limiter_disabled_drops_alimiter():
    cfg = {**AUDIO_CFG, "limiter": {"enabled": False}}
    chain = build_audio_chain(cfg, MEASURED)
    assert "alimiter" not in chain, chain


def test_style_seco_has_audio_section():
    audio = load_style("seco").get("audio")
    assert audio, "styles/seco.json sem seção audio"
    for key in ("target_i", "target_tp", "target_lra", "limiter"):
        assert key in audio, f"audio sem '{key}'"
    chain = build_audio_chain(audio, MEASURED)
    assert chain.startswith(f"loudnorm=I={audio['target_i']}:TP={audio['target_tp']}")


def test_parse_loudnorm_json_from_stderr():
    stderr = "lixo de log\n[Parsed_loudnorm_0 @ 0x600] \n" + json.dumps(
        {"input_i": "-23.47", "input_tp": "-3.55", "input_lra": "10.1",
         "input_thresh": "-34.2", "target_offset": "0.4"}, indent=2)
    parsed = parse_loudnorm_json(stderr)
    assert parsed["input_i"] == "-23.47", parsed


def test_music_gain_targets_bed_lufs():
    # músicas do canal variam 6 dB entre si; o ganho sai da medição para o
    # bed cair sempre no mesmo nível relativo à voz (-14 LUFS)
    assert abs(music_gain_db({"bed_lufs": -36.0}, measured_i=-8.67)
               - (-27.33)) < 0.01


def test_music_chain_volume_and_fade():
    cfg = {"bed_lufs": -36.0, "fade_out": 1.5}
    chain = build_music_chain(cfg, total=57.5, measured_i=-8.5)
    assert chain == "volume=-27.5dB,aresample=48000,afade=t=out:st=56.0:d=1.5", chain


def test_music_chain_without_fade():
    chain = build_music_chain({"bed_lufs": -36.0, "fade_out": 0}, 30.0, -10.0)
    assert "afade" not in chain and "volume=-26.0dB" in chain


def test_resolve_music_file_default_and_named():
    cfg = {"default": "musicafundo3", "dir": "assets/music"}
    p = resolve_music_file(cfg, None)
    assert p.name == "musicafundo3.m4a" and p.exists(), p
    p2 = resolve_music_file(cfg, "musicafundo2")
    assert p2.name == "musicafundo2.m4a" and p2.exists(), p2


def test_style_seco_has_music():
    music = load_style("seco").get("music")
    assert music, "styles/seco.json sem seção music"
    assert music["default"] == "musicafundo3"
    assert music["bed_lufs"] <= -30, "bed alto demais vira briga com a voz"


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
