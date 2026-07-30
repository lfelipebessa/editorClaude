"""Testes da cadeia de cor do adaptador ffmpeg (dirigida pelo style file).

Rodar: .venv/bin/python tests/test_color_chain.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "adapters"))

from render_ffmpeg import build_color_chain, load_style


def test_adjust_only_chain():
    cfg = {"scope": "camera", "lut": None,
           "adjust": {"exposure_ev": 0.05, "contrast": 1.06,
                      "saturation": 1.16, "gamma": 1.0}}
    chain = build_color_chain(cfg)
    assert chain == "exposure=exposure=0.05,eq=contrast=1.06:saturation=1.16", chain
    assert "lut3d" not in chain and "gamma" not in chain


def test_neutral_adjusts_produce_empty_chain():
    cfg = {"lut": None, "adjust": {"exposure_ev": 0.0, "contrast": 1.0,
                                   "saturation": 1.0, "gamma": 1.0}}
    assert build_color_chain(cfg) == ""


def test_lut_comes_first(tmp_lut=Path("/tmp/editorclaude_test.cube")):
    tmp_lut.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n"
                       "0 0 1\n1 0 1\n0 1 1\n1 1 1\n")
    cfg = {"lut": str(tmp_lut), "adjust": {"saturation": 1.1}}
    chain = build_color_chain(cfg)
    assert chain.startswith(f"lut3d=file={tmp_lut}"), chain
    assert chain.endswith("eq=saturation=1.1"), chain
    tmp_lut.unlink()


def test_missing_lut_fails_clearly():
    cfg = {"lut": "assets/luts/nao_existe.cube", "adjust": {}}
    try:
        build_color_chain(cfg)
    except SystemExit as e:
        assert "nao_existe" in str(e)
    else:
        raise AssertionError("LUT inexistente devia falhar")


def test_curve_s_and_vibrance_chain():
    cfg = {"scope": "camera", "lut": None,
           "adjust": {"exposure_ev": 0.06, "contrast": 1.0, "saturation": 1.0,
                      "gamma": 1.0,
                      "curve_s": "0/0 0.22/0.19 0.5/0.52 0.78/0.82 1/1",
                      "vibrance": 0.35}}
    chain = build_color_chain(cfg)
    assert chain == ("curves=master='0/0 0.22/0.19 0.5/0.52 0.78/0.82 1/1',"
                     "vibrance=intensity=0.35,exposure=exposure=0.06"), chain


def test_curve_vibrance_neutral_when_absent():
    cfg = {"lut": None, "adjust": {"exposure_ev": 0.0, "contrast": 1.0,
                                   "saturation": 1.0, "gamma": 1.0,
                                   "curve_s": None, "vibrance": 0.0}}
    assert build_color_chain(cfg) == ""


def test_curves_come_before_eq():
    cfg = {"lut": None,
           "adjust": {"curve_s": "0/0 1/1", "vibrance": 0.2, "contrast": 1.1}}
    chain = build_color_chain(cfg)
    assert "curves=" in chain and "vibrance=" in chain and "eq=" in chain, chain
    assert chain.index("curves=") < chain.index("vibrance=") < chain.index("eq="), chain


def test_style_seco_has_color_section():
    color = load_style("seco").get("color")
    assert color, "styles/seco.json sem seção color"
    assert color["scope"] == "camera", "cor é só para footage de câmera"
    assert "adjust" in color and "lut" in color
    chain = build_color_chain(color)
    assert "curves=" in chain and "vibrance=" in chain, \
        f"grade do seco devia usar curva S + vibrance: {chain!r}"


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
