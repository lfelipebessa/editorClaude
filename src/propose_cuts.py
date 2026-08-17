"""Lê o transcript de um vídeo longo e PROPÕE N cortes para rede social.

Este é o passo que ainda não era script: escolher os trechos. O enquadramento,
o corte na palavra e o render já eram automáticos — o que travava a escala era
alguém ler o transcript inteiro e decidir o que vira Reel.

A estrutura que sai daqui é a aprovada pelo Luiz em 2026-08-16 (ver a skill
`rough-cut`, seção 3d): **gancho (o ponto alto puxado do FIM do vídeo) →
problema → passos → execução → payoff → CTA**. O gancho dá o gostinho do
resultado antes de qualquer explicação — é o que faz o corte segurar.

**O padrão NÃO chama API.** Quem escolhe os trechos é o agente que já está na
sessão — no Claude Code o modelo é o próprio Claude que está lendo isto, então
uma chamada de API seria pagar duas vezes pelo mesmo julgamento, com uma chave
a mais para gerenciar e mais um jeito de quebrar. O script monta o briefing
(transcrição + regras + schema) e o agente responde:

    python src/propose_cuts.py output/transcript_<slug>.json -n 3
    # -> briefing no stdout; o agente devolve o JSON das propostas

`--api` existe para quando NÃO há agente na sessão: cron, servidor, ou o
frontend hospedado. Aí sim precisa de ANTHROPIC_API_KEY ou `ant auth login`:

    python src/propose_cuts.py output/transcript_<slug>.json -n 3 --api \
        -o output/propostas_<slug>.json

O que sai daqui é PROPOSTA, com tempos aproximados. Quem encosta na borda da
palavra, detecta repetição e escreve a receita é o src/build_recipes.py — a
separação é de propósito: julgamento editorial no modelo, precisão no código.
"""

import argparse
import json
import sys
from pathlib import Path

MODEL = "claude-opus-5"

PAPEIS = ["gancho", "problema", "passo", "execucao", "payoff", "cta"]

SCHEMA = {
    "type": "object",
    "properties": {
        "cortes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "identificador curto em snake_case, ex.: github_sem_git",
                    },
                    "tema": {
                        "type": "string",
                        "description": "o corte em uma frase, do ponto de vista de quem assiste",
                    },
                    "por_que_funciona": {
                        "type": "string",
                        "description": "por que este gancho segura nos 3 primeiros segundos",
                    },
                    "segmentos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "papel": {"type": "string", "enum": PAPEIS},
                                "label": {
                                    "type": "string",
                                    "description": "o que se ouve neste trecho, em poucas palavras",
                                },
                            },
                            "required": ["start", "end", "papel", "label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["slug", "tema", "por_que_funciona", "segmentos"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cortes"],
    "additionalProperties": False,
}

INSTRUCOES = """\
Você está montando cortes verticais (Reels/Shorts) a partir da transcrição de \
um vídeo longo do YouTube. Cada corte precisa funcionar sozinho, para alguém \
que nunca viu o vídeo original.

# A estrutura (obrigatória, nesta ordem)

1. GANCHO — o ponto alto do vídeo, puxado do FIM. Abra com o resultado pronto,
   nunca com a introdução do vídeo original. O espectador precisa ver aonde
   isso chega antes de ouvir qualquer explicação.
2. PROBLEMA — a dor que o resultado resolve.
3. PASSOS — o caminho, em ordem.
4. EXECUÇÃO — o momento em que a coisa acontece de verdade.
5. PAYOFF — o resultado, agora mostrado por inteiro.
6. CTA — o fecho falado que já existe na transcrição.

Nem todo corte tem os seis papéis, mas GANCHO e PAYOFF são obrigatórios, e o
gancho vem sempre de um trecho posterior ao miolo do corte.

# Regras duras

- Só use fala que EXISTE na transcrição. Nunca invente frase.
- Cada segmento é um trecho contínuo: um `start` e um `end` no tempo do vídeo.
  Os segmentos de um mesmo corte NÃO podem se sobrepor no tempo.
- Nada de bastidor: fala sobre a gravação ("o arquivo corrompeu", "a gente já
  acabou o vídeo", "deixa eu ajeitar a câmera") não entra. Num Reel solto,
  o espectador não tem contexto para isso e a frase soa quebrada.
- Não repita a mesma ideia em dois segmentos do mesmo corte. Se dois trechos
  dizem a mesma coisa, escolha o melhor e descarte o outro.
- Corte em frase inteira. Não termine num "e aí", "mas", "então" solto — a
  borda exata é ajustada depois, mas o trecho já deve fazer sentido fechado.
- Cada corte precisa de um tema DIFERENTE dos outros. Não fatie o mesmo assunto
  em variações; procure os assuntos distintos que o vídeo cobre.

# Duração

Some `end - start` de todos os segmentos de um corte. O total (a duração da
FONTE) deve ficar entre {dur_min:.0f} e {dur_max:.0f} segundos — o corte é
acelerado {speed}x depois, então isso vira um Reel de {alvo_min:.0f}s a \
{alvo_max:.0f}s.

# Saída

{n} cortes. Para cada um: slug, tema, por que o gancho funciona, e a lista de
segmentos com `papel` e um `label` curto do que se ouve.
"""


def carregar_transcript(path: Path) -> tuple[str, float]:
    d = json.loads(path.read_text())
    linhas = [
        f"{s['start']:7.1f}-{s['end']:7.1f} {s['text'].strip()}"
        for s in d["segments"]
    ]
    return "\n".join(linhas), d["segments"][-1]["end"]


def montar_prompt(transcricao: str, total: float, n: int, speed: float,
                  dur_min: float, dur_max: float) -> str:
    instrucoes = INSTRUCOES.format(
        n=n, speed=speed, dur_min=dur_min, dur_max=dur_max,
        alvo_min=dur_min / speed, alvo_max=dur_max / speed,
    )
    return (
        f"{instrucoes}\n\n"
        f"# Transcrição ({total / 60:.0f} min, tempos em segundos)\n\n"
        f"{transcricao}\n"
    )


def chamar_api(prompt: str) -> dict:
    try:
        import anthropic
    except ImportError:
        sys.exit("SDK ausente: .venv/bin/pip install anthropic\n"
                 "(ou rode sem --api: o agente da sessão responde o briefing)")

    client = anthropic.Anthropic()  # resolve ANTHROPIC_API_KEY ou perfil `ant`
    try:
        # streaming porque a resposta é longa: sem ele o SDK estoura o timeout
        with client.messages.stream(
            model=MODEL,
            max_tokens=64000,
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        sys.exit(
            "sem credencial válida. Duas saídas:\n"
            "  export ANTHROPIC_API_KEY=...   (chave da console)\n"
            "  ant auth login                 (perfil, sem chave no ambiente)\n"
            "Sem --api o briefing sai no stdout e o agente da sessão responde.")
    except anthropic.RateLimitError:
        sys.exit("rate limit da API — tente de novo em alguns minutos.")

    if msg.stop_reason == "refusal":
        sys.exit(f"pedido recusado: {msg.stop_details}")
    texto = next(b.text for b in msg.content if b.type == "text")
    print(f"  modelo {msg.model} | {msg.usage.output_tokens} tokens de saída",
          file=sys.stderr)
    return json.loads(texto)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("-n", "--cortes", type=int, default=3)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--api", action="store_true",
                    help="chama a API em vez de entregar o briefing ao agente "
                         "da sessão (só faz sentido sem agente: cron, servidor, "
                         "frontend)")
    ap.add_argument("--speed", type=float, default=1.2)
    ap.add_argument("--dur-min", type=float, default=58.0,
                    help="duração mínima da FONTE, em segundos")
    ap.add_argument("--dur-max", type=float, default=74.0)
    args = ap.parse_args()

    transcricao, total = carregar_transcript(args.transcript)
    prompt = montar_prompt(transcricao, total, args.cortes, args.speed,
                           args.dur_min, args.dur_max)

    if not args.api:
        print(prompt)
        print("\n# Formato de resposta (JSON, este schema exato)\n")
        print(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
        return

    propostas = chamar_api(prompt)
    saida = json.dumps(propostas, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(saida)
        print(f"{len(propostas['cortes'])} cortes -> {args.output}")
    else:
        print(saida)


if __name__ == "__main__":
    main()
