"""Testes da cadeia de áudio do adaptador ffmpeg (dirigida pelo style file).

Rodar: .venv/bin/python tests/test_audio_chain.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from render_ffmpeg import build_audio_chain, load_style, parse_loudnorm_json

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
