"""Style do canal: o que muda de gosto vive em styles/*.json, não no código.

Regra do repo (CLAUDE.md): gosto de corte, cor, loudness e música NÃO são
código — são o style. Este módulo é a única porta de entrada para ele.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = PROJECT_ROOT / "styles"


def load_style(style_name: str) -> dict:
    path = STYLES_DIR / f"{style_name}.json"
    if not path.exists():
        sys.exit(f"style não encontrado: {path}")
    return json.loads(path.read_text())


def pick_platform(style: dict, platform: str) -> dict:
    platforms = style.get("platforms", {})
    if platform not in platforms:
        sys.exit(f"plataforma '{platform}' não existe no style "
                 f"(disponíveis: {', '.join(sorted(platforms))})")
    return platforms[platform]


def resolve_music_file(music_cfg: dict, name: str | None) -> Path:
    """None -> música default do canal; nome -> assets/music/<nome>.m4a;
    caminho existente -> usado como veio."""
    if name and Path(name).expanduser().exists():
        return Path(name).expanduser()
    chosen = name or music_cfg.get("default", "")
    path = PROJECT_ROOT / music_cfg.get("dir", "assets/music") / f"{chosen}.m4a"
    if not path.exists():
        sys.exit(f"música não encontrada: {path} (biblioteca: "
                 f"{sorted(p.stem for p in path.parent.glob('*.m4a'))})")
    return path
