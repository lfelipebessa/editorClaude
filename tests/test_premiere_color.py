"""Testes da cadeia de cor do adaptador Premiere (style -> Lumetri Color).

Rodar: .venv/bin/python tests/test_premiere_color.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))
sys.path.insert(0, str(Path(__file__).parent.parent / "adapters" / "premiere_mcp"))

from render_ffmpeg import load_style
from render_premiere import (build_copy_effects_jsx, build_lumetri_jsx,
                             lumetri_from_style, noise_from_style,
                             parse_tool_payload)


def test_lumetri_from_style_seco():
    # valores calibrados pelo usuário no Premiere em 2026-07-30 (clipe 1 da
    # rough_cut_dji_v4_audio) e traduzidos de volta para o style
    params = lumetri_from_style(load_style("seco")["color"])
    assert params == {"Exposure": -0.2, "Contrast": 16, "Shadows": -11,
                      "Highlights": -39, "Whites": 5, "Blacks": -12,
                      "Saturation": 124, "Vibrance": 58, "Sharpen": 30}, params


def test_whites_blacks_pass_through_to_lumetri():
    cfg = {"lut": None, "adjust": {"whites": 5, "blacks": -12.4}}
    params = lumetri_from_style(cfg)
    assert params == {"Whites": 5, "Blacks": -12}, params


def test_noise_from_style_seco():
    assert noise_from_style(load_style("seco")["color"]) == 15


def test_noise_neutral_returns_none():
    assert noise_from_style({"finish": {"grain": 0}}) is None
    assert noise_from_style({}) is None


def test_jsx_adds_noise_effect_when_requested():
    # o Noise do Premiere 2026 é o efeito novo estilo grain:
    # Intensity + Saturation (0 = grain só no luma), não "Amount of Noise"
    jsx = build_lumetri_jsx({"Exposure": 0.07}, noise_amount=15)
    assert '"Noise"' in jsx, "devia garantir o efeito Noise no clipe"
    assert '"Intensity"' in jsx and "setValue(15, true)" in jsx
    assert '"Saturation"' in jsx and "setValue(0, true)" in jsx
    jsx_sem = build_lumetri_jsx({"Exposure": 0.07})
    assert '"Noise"' not in jsx_sem and '"Intensity"' not in jsx_sem


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


def test_copy_jsx_copies_by_index_not_by_name():
    # curvas/HSL vivem em blobs e propriedades sem nome (displayName vazio ou
    # duplicado) — cópia por displayName corrompe; por índice preserva tudo
    jsx = build_copy_effects_jsx(["Lumetri Color", "Noise"])
    assert "properties[j].getValue()" in jsx or ".properties[j]" in jsx, jsx
    assert '"Lumetri Color"' in jsx and '"Noise"' in jsx
    assert "sourceIdx" in jsx and "JSON.stringify" in jsx
    # cores empacotadas em 64-bit (pickers) perdem precisão no ExtendScript e
    # viram lixo no setValue — a cópia precisa pular números acima de 2^32
    assert "4294967295" in jsx, "faltou guard contra números 64-bit imprecisos"


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
