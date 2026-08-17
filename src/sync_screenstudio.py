"""Mede o offset de cada SESSÃO bruta do bundle .screenstudio dentro do export.

O Screen Studio abre uma sessão nova a cada pausa da gravação (channel-*-0,
-1, -2…) e o export é a concatenação delas. Quem fala no relógio do export é o
transcript; quem tem a imagem boa são os canais brutos. Este script liga os
dois — e a ligação precisa ser MEDIDA: somar as durações erra por centenas de
ms (sobreposição na emenda), e alguns quadros de erro já estouram o sincronismo
labial da metade de baixo do Reel.

Método: correlação cruzada do envelope de energia do áudio do microfone de cada
sessão contra o do export. Passada grossa (200 Hz) acha a região; três janelas
de 20 s (10%, 50%, 85% da sessão) refinam a 2000 Hz e provam que o offset é
CONSTANTE — se as três discordarem, há drift e o corte não pode confiar no
mapeamento.

Uso:
    python src/sync_screenstudio.py <bundle.screenstudio> <export.mp4>
        [-o output/sync_<slug>.json]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

COARSE_SR = 200
FINE_SR = 2000
WINDOW = 20.0
FINE_FRACTIONS = (0.1, 0.5, 0.85)
TOLERANCE = 0.030   # s: espalhamento máximo entre as três janelas


def envelope(path: str, sr: int, ss: float | None = None,
             t: float | None = None) -> np.ndarray:
    """PCM mono 16k -> envelope RMS em `sr` Hz."""
    cmd = ["/opt/homebrew/bin/ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss}"]
    if t is not None:
        cmd += ["-t", f"{t}"]
    cmd += ["-i", path, "-map", "0:a:0", "-ac", "1", "-ar", "16000",
            "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = 16000 // sr
    n = len(x) // win * win
    if n == 0:
        sys.exit(f"áudio vazio em {path} (ss={ss}, t={t})")
    return np.sqrt((x[:n].reshape(-1, win) ** 2).mean(axis=1))


def best_lag(needle: np.ndarray, hay: np.ndarray) -> tuple[int, float]:
    """Lag (em amostras) do melhor encaixe + coeficiente normalizado local."""
    size = 1 << (len(hay) + len(needle) - 1).bit_length()
    a = np.fft.rfft(hay - hay.mean(), size)
    b = np.fft.rfft((needle - needle.mean())[::-1], size)
    corr = np.fft.irfft(a * b, size)[:len(hay)]
    idx = int(np.argmax(corr))
    seg = hay[max(0, idx - len(needle) + 1):idx + 1]
    denom = (np.linalg.norm(seg - seg.mean())
             * np.linalg.norm(needle - needle.mean()) + 1e-9)
    return idx - (len(needle) - 1), float(corr[idx] / denom)


def session_files(rec: Path, kind: str) -> list[Path]:
    return sorted(rec.glob(f"channel-*-{kind}-*.m3u8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("export", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()

    rec = args.bundle / "recording"
    mics = session_files(rec, "microphone")
    if not mics:
        sys.exit(f"nenhum channel-*-microphone-*.m3u8 em {rec}")

    hay_coarse = envelope(str(args.export), COARSE_SR)
    print(f"export: {len(hay_coarse) / COARSE_SR:.2f}s")

    sessions = []
    for i, mic in enumerate(mics):
        nee = envelope(str(mic), COARSE_SR)
        dur = len(nee) / COARSE_SR
        lag, _ = best_lag(nee, hay_coarse)
        coarse = lag / COARSE_SR

        fine = []
        for frac in FINE_FRACTIONS:
            local = dur * frac
            n = envelope(str(mic), FINE_SR, local, WINDOW)
            hs = coarse + local - 2.0
            h = envelope(str(args.export), FINE_SR, hs, WINDOW + 4.0)
            lag, peak = best_lag(n, h)
            fine.append((hs + lag / FINE_SR - local, peak))

        offs = [f[0] for f in fine]
        spread = max(offs) - min(offs)
        offset = round(float(np.median(offs)), 3)
        status = "ok" if spread <= TOLERANCE else "DRIFT"
        print(f"sessão {i}: dur={dur:7.2f}s  offset={offset:8.3f}s  "
              f"espalhamento={spread * 1000:5.1f}ms  "
              f"r={min(f[1] for f in fine):.3f}  [{status}]")
        if spread > TOLERANCE:
            print("   ! as janelas discordam: há drift entre bruto e export — "
                  "não use este offset para a metade de baixo do Reel")
        sessions.append({"session": i, "offset": offset, "duration": round(dur, 3),
                         "spread_ms": round(spread * 1000, 1)})

    out = {"bundle": str(args.bundle), "export": str(args.export),
           "sessions": sessions}
    if args.output:
        args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print(f"\nsalvo em {args.output}")


if __name__ == "__main__":
    main()
