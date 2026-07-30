"""Testes da cadeia de cor do adaptador Premiere (style -> Lumetri Color).

Rodar: .venv/bin/python tests/test_premiere_color.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
sys.path.insert(0, str(Path(__file__).parent.parent / "adapters" / "premiere_mcp"))

from render_ffmpeg import load_style
from render_premiere import (build_lumetri_jsx, lumetri_from_style,
                             noise_from_style, parse_tool_payload)


def test_lumetri_from_style_seco():
    params = lumetri_from_style(load_style("seco")["color"])
    assert params == {"Exposure": 0.07, "Contrast": 13, "Shadows": -12,
                      "Highlights": 20, "Saturation": 106, "Vibrance": 58,
                      "Sharpen": 30}, params


def test_noise_from_style_seco():
    assert noise_from_style(load_style("seco")["color"]) == 4


def test_noise_neutral_returns_none():
    assert noise_from_style({"finish": {"grain": 0}}) is None
    assert noise_from_style({}) is None


def test_jsx_adds_noise_effect_when_requested():
    jsx = build_lumetri_jsx({"Exposure": 0.07}, noise_amount=4)
    assert '"Noise"' in jsx, "devia garantir o efeito Noise no clipe"
    assert '"Amount of Noise"' in jsx and "setValue(4, true)" in jsx
    assert '"Use Color Noise"' in jsx, "grain deve ser só luma (color noise off)"
    jsx_sem = build_lumetri_jsx({"Exposure": 0.07})
    assert '"Noise"' not in jsx_sem and "Amount of Noise" not in jsx_sem


def test_lumetri_neutral_returns_none():
    cfg = {"scope": "camera", "lut": None,
           "adjust": {"exposure_ev": 0.0, "contrast": 1.0, "saturation": 1.0,
                      "gamma": 1.0, "curve_s": None, "vibrance": 0.0}}
    assert lumetri_from_style(cfg) is None


def test_lumetri_eq_only_maps_to_contrast_saturation():
    cfg = {"lut": None, "adjust": {"exposure_ev": 0.0, "contrast": 1.06,
                                   "saturation": 1.16, "gamma": 1.0}}
    params = lumetri_from_style(cfg)
    assert params == {"Contrast": 6, "Saturation": 116}, params


def test_jsx_sets_every_param_and_reports_json():
    jsx = build_lumetri_jsx({"Exposure": 0.06, "Vibrance": 35})
    assert 'getVideoEffectByName("Lumetri Color")' in jsx
    assert 'p.displayName === "Exposure"' in jsx and "setValue(0.06, true)" in jsx
    assert 'p.displayName === "Vibrance"' in jsx and "setValue(35, true)" in jsx
    assert "JSON.stringify" in jsx and "applied" in jsx


def test_jsx_reuses_existing_lumetri_instead_of_stacking():
    # re-rodar a grade não pode empilhar um segundo Lumetri no clipe
    jsx = build_lumetri_jsx({"Exposure": 0.06})
    assert '=== "Lumetri Color"' in jsx and "addVideoEffect" in jsx
    assert jsx.index('=== "Lumetri Color"') < jsx.rindex("addVideoEffect"), \
        "devia procurar Lumetri existente antes de adicionar outro"


def test_parse_tool_payload_survives_non_dict_json():
    # execute_extendscript devolve string JSON dupla-codificada; nunca pode quebrar
    payload = parse_tool_payload(['"undefined"'])
    assert isinstance(payload, dict), payload
    payload = parse_tool_payload(['{"success": true, "applied": 3}'])
    assert payload.get("applied") == 3


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
