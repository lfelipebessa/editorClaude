"""Adaptador Premiere Pro MCP — ESQUELETO, não funcional.

BLOQUEADO: o Adobe Premiere Pro não está instalado nesta máquina.
Dependência: https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP

Quando desbloquear, este script consumirá a cut-list (contrato no README da raiz)
e montará a sequência no Premiere via MCP — um subclip por segmento, na ordem dada.
"""

import argparse
import json
import sys
from pathlib import Path


def render(video: Path, cutlist: dict) -> None:
    raise NotImplementedError(
        "Adaptador Premiere MCP bloqueado: instale o Adobe Premiere Pro e o MCP "
        "server github.com/hetpatel-11/Adobe_Premiere_Pro_MCP antes de implementar."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    args = parser.parse_args()

    cutlist = json.loads(args.cutlist.read_text())
    if cutlist.get("version") != 1:
        sys.exit(f"versão de cut-list não suportada: {cutlist.get('version')}")
    render(args.video, cutlist)


if __name__ == "__main__":
    main()
