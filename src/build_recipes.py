"""Transforma PROPOSTAS de corte em receitas prontas para o reel_screencam.

O modelo (ou a mão) propõe trechos com tempos aproximados; aqui eles viram
cortes de verdade. Tudo o que este script faz foi aprendido apanhando no
primeiro lote de cortes (2026-08-16) — cada regra existe porque um render saiu
errado por falta dela:

- **encosta na palavra**: tempo aproximado corta no meio da sílaba. As bordas
  vão para o início/fim da palavra mais próxima, com o mesmo respiro do style
  (pad de saída maior que o de entrada: sobra de fim é recuperável, falta não).
- **tira palavra órfã**: palavra de abertura que termina em `.` `?` `!` é rabo
  da frase anterior; palavra de fecho que é conjunção solta é começo da próxima.
  As duas fazem o corte soar quebrado.
- **avisa de sobreposição** entre segmentos do mesmo corte (o espectador ouve a
  mesma fala duas vezes) e de **texto repetido** (a mesma ideia em dois
  segmentos — o modelo faz isso quando o vídeo repete o assunto).
- **confere a duração** contra o alvo depois da aceleração.

Uso:
    python src/build_recipes.py output/propostas_<slug>.json \
        output/transcript_<slug>.json --base output/reel_<algum>_<slug>.json \
        --slug <slug>

A `--base` é uma receita existente do mesmo bruto: dela saem as fontes (tela,
câmera, áudio), os offsets de sessão e o enquadramento padrão. Os crops por
segmento continuam sendo escolha humana — ver a folha de contato do
reel_screencam.
"""

import argparse
import json
import re
import sys
from pathlib import Path

PAD_IN = 0.08
PAD_OUT = 0.15   # pad_after do style
ORFAS_FIM = {"e", "aí", "mas", "o", "a", "se", "eu", "então", "que", "é", "de",
             "com", "para", "pra", "no", "na", "um", "uma", "aqui", "você",
             "já", "mais", "também"}
# palavras que aparecem em qualquer fala e não dizem do que o trecho trata
FUNCIONAIS = {"gente", "aqui", "para", "pra", "você", "vocês", "isso", "esse",
              "essa", "muito", "mais", "coisa", "coisas", "então", "porque",
              "quando", "onde", "como", "todo", "toda", "cada", "outro",
              "fazer", "faz", "vai", "vou", "está", "estar", "ser", "tem",
              "ter", "seu", "sua", "meu", "minha", "nosso", "nossa", "que",
              "com", "uma", "aqui", "vamos", "consegue", "conseguir"}


def limpar(tok: str) -> str:
    return re.sub(r"[^\wçãõáéíóúâêôà]", "", tok.lower())


def palavras(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s.get("words", [])
            if w.get("start") is not None]


def encostar(ws: list[dict], a: float, b: float) -> tuple[float, float, str] | None:
    """Encosta (a, b) nas bordas de palavra e devolve (start, end, texto)."""
    dentro = [w for w in ws if w["start"] >= a - 0.30 and w["end"] <= b + 0.05]
    while dentro and re.search(r"[.?!]$", dentro[0]["word"]):
        dentro.pop(0)
    while dentro and limpar(dentro[-1]["word"]) in ORFAS_FIM:
        dentro.pop()
    if not dentro:
        return None
    return (round(dentro[0]["start"] - PAD_IN, 2),
            round(dentro[-1]["end"] + PAD_OUT, 2),
            " ".join(w["word"] for w in dentro))


def sobreposicoes(segs: list[dict]) -> list[str]:
    """Segmentos do mesmo corte que se cruzam no tempo da FONTE."""
    avisos = []
    ordenados = sorted(range(len(segs)), key=lambda i: segs[i]["start"])
    for x, y in zip(ordenados, ordenados[1:]):
        if segs[y]["start"] < segs[x]["end"]:
            avisos.append(
                f"segmentos {x} e {y} se sobrepõem "
                f"({segs[y]['start']:.2f} < {segs[x]['end']:.2f}) — "
                f"a mesma fala vai tocar duas vezes")
    return avisos


def repeticoes(textos: list[str]) -> list[str]:
    """Pares de segmentos que dizem quase a mesma coisa.

    Mede CONTENÇÃO (quanto do trecho curto cabe no longo), não Jaccard: a
    repetição que atrapalha é a de um trecho curto engolido por um mais longo,
    e o Jaccard dilui isso no tamanho do maior. Só palavras de conteúdo entram
    — sem filtrar, dois trechos do mesmo assunto disparam por "gente", "aqui",
    "para". É heurística de vocabulário, não de sentido: o limiar (0.7) foi
    calibrado no lote de 2026-08-16 para pegar o engolimento real sem acusar
    dois trechos que só falam do mesmo assunto. Aviso, não erro.
    """
    avisos = []
    conjuntos = [{p for p in map(limpar, txt.split())
                  if len(p) > 3 and p not in FUNCIONAIS}
                 for txt in textos]
    for i in range(len(conjuntos)):
        for j in range(i + 1, len(conjuntos)):
            a, b = conjuntos[i], conjuntos[j]
            if min(len(a), len(b)) < 4:
                continue
            contencao = len(a & b) / min(len(a), len(b))
            if contencao >= 0.7:
                avisos.append(
                    f"segmentos {i} e {j} podem repetir a ideia ({contencao:.0%} do "
                    f"trecho menor está no maior) — leia os dois e confira")
    return avisos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("propostas", type=Path)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--base", type=Path, required=True,
                    help="receita existente do mesmo bruto (fontes + offsets)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--outdir", type=Path, default=Path("output"))
    ap.add_argument("--dur-min", type=float, default=58.0)
    ap.add_argument("--dur-max", type=float, default=74.0)
    args = ap.parse_args()

    ws = palavras(json.loads(args.transcript.read_text()))
    base = json.loads(args.base.read_text())
    speed = base.get("speed", 1.2)
    propostas = json.loads(args.propostas.read_text())

    problemas = 0
    for corte in propostas["cortes"]:
        print(f"\n{'=' * 72}\n# {corte['slug']} — {corte['tema']}")
        print(f"  gancho: {corte['por_que_funciona']}")
        segs, textos = [], []
        for p in corte["segmentos"]:
            encostado = encostar(ws, p["start"], p["end"])
            if encostado is None:
                print(f"  !! nada aproveitável em {p['start']}-{p['end']} "
                      f"({p['label']})")
                problemas += 1
                continue
            s, e, texto = encostado
            segs.append({"start": s, "end": e,
                         "label": f"{p['papel']}: {p['label']}"})
            textos.append(texto)
            print(f"  {s:7.2f} {e:7.2f} ({e - s:5.2f}s) {p['papel']}: {p['label']}")
            print(f"          {texto}")

        for aviso in sobreposicoes(segs) + repeticoes(textos):
            print(f"  !! {aviso}")
            problemas += 1

        total = sum(s["end"] - s["start"] for s in segs)
        fora = "" if args.dur_min <= total <= args.dur_max else "  << FORA DO ALVO"
        if fora:
            problemas += 1
        print(f"  -- fonte {total:.1f}s -> {speed}x = {total / speed:.1f}s"
              f" final{fora}")

        receita = {
            "_nota": f"{corte['tema']} (proposto por src/propose_cuts.py)",
            "audio": base["audio"],
            "top": {"sessions": base["top"]["sessions"],
                    "crop": base["top"]["crop"]},
            "bottom": {"sessions": base["bottom"]["sessions"],
                       "crop": base["bottom"]["crop"]},
            "top_h": base.get("top_h", 960),
            "speed": speed,
            "segments": segs,
        }
        for s in receita["top"]["sessions"] + receita["bottom"]["sessions"]:
            s.pop("duration", None)
        destino = args.outdir / f"reel_{corte['slug']}_{args.slug}.json"
        destino.write_text(json.dumps(receita, ensure_ascii=False, indent=2) + "\n")
        print(f"  -> {destino}")

    print(f"\n{problemas} ponto(s) para revisar antes de renderizar."
          if problemas else "\nNenhum aviso — pode render.")
    print("Próximo: reel_screencam.py <receita> --contact-sheet folha.jpg")
    sys.exit(0)


if __name__ == "__main__":
    main()
