"""Adaptador Premiere Pro MCP: monta a cut-list como timeline no Premiere.

Consome apenas o contrato da cut-list (ver README da raiz) — o adaptador não
decide corte, só executa: importa o vídeo fonte, cria projeto+sequência novos e
coloca um subclip [start, end) por segmento, na ordem, via add_to_timeline_batch.

Fala MCP (JSON-RPC 2.0 por linha, stdio) direto com o servidor Node do
github.com/hetpatel-11/Adobe_Premiere_Pro_MCP (clonado em vendor/). Requer o
Premiere aberto com o painel MCP Bridge (CEP) iniciado — ver README deste dir.

Uso:
    python adapters/premiere_mcp/render_premiere.py video.mp4 output/cutlist.json \
        [--project-dir ~/Documents] [--project-name EditorClaude_teste] [--dry-run]
"""

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVER_ENTRY = REPO_ROOT / "vendor/Adobe_Premiere_Pro_MCP/dist/index.js"
BRIDGE_TEMP_DIR = "/tmp/premiere-mcp-bridge"
PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPStdioClient:
    """Cliente mínimo do Model Context Protocol sobre stdio (JSON-RPC por linha)."""

    def __init__(self, command: list[str], env: dict, timeout: float = 120.0):
        self.command = command
        self.env = env
        self.timeout = timeout
        self.proc = None
        self._id = 0
        self._stderr_tail = []

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={**os.environ, **self.env},
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "editorclaude-render-premiere", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})
        server = result.get("serverInfo", {})
        print(f"conectado ao MCP server: {server.get('name')} {server.get('version', '')}")

    def _drain_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr_tail = (self._stderr_tail + [line.rstrip()])[-20:]

    def _send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        self._id += 1
        req_id = self._id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        result = {}

        def read():
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise MCPError(
                        "servidor MCP encerrou. stderr:\n" + "\n".join(self._stderr_tail))
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("id") == req_id:
                    result["msg"] = msg
                    return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(self.timeout)
        if "msg" not in result:
            raise MCPError(f"timeout ({self.timeout}s) aguardando resposta de {method} — "
                           "o painel MCP Bridge está iniciado no Premiere?")
        msg = result["msg"]
        if "error" in msg:
            raise MCPError(f"{method} falhou: {msg['error'].get('message')}")
        return msg.get("result", {})

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        texts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text"]
        payload = {}
        for text in texts:
            try:
                payload = json.loads(text)
                break
            except (json.JSONDecodeError, TypeError):
                continue
        if result.get("isError") or payload.get("success") is False:
            detail = payload.get("error") or payload.get("message") or " ".join(texts)[:500]
            raise MCPError(f"tool {name} falhou: {detail}")
        return payload if payload else {"raw": " ".join(texts)}

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.terminate()


def find_key(obj, *keys):
    """Procura a primeira ocorrência de qualquer das chaves, em qualquer nível."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            found = find_key(v, *keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, *keys)
            if found is not None:
                return found
    return None


def find_item_id_by_name(items_payload, media_name: str):
    """Localiza o id do project item cujo nome bate com o arquivo importado."""
    matches = []

    def walk(obj):
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("mediaPath") or ""
            item_id = obj.get("id") or obj.get("nodeId") or obj.get("itemId")
            if item_id and media_name.lower() in str(name).lower():
                matches.append(str(item_id))
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(items_payload)
    return matches[0] if matches else None


def build_batch(cutlist: dict, item_id: str) -> list[dict]:
    clips, cursor = [], 0.0
    for seg in cutlist["segments"]:
        clips.append({
            "projectItemId": item_id,
            "trackIndex": 0,
            "time": round(cursor, 3),
            "sourceInPoint": seg["start"],
            "sourceOutPoint": seg["end"],
        })
        cursor += seg["end"] - seg["start"]
    return clips


def render(video: Path, cutlist: dict, project_dir: Path, project_name: str,
           sequence_name: str, timeout: float, use_open_project: bool = False) -> None:
    client = MCPStdioClient(
        ["node", str(SERVER_ENTRY)],
        env={"PREMIERE_TEMP_DIR": BRIDGE_TEMP_DIR},
        timeout=timeout,
    )
    client.start()
    try:
        if use_open_project:
            info = client.call_tool("get_project_info", {})
            print(f"usando projeto já aberto: {info.get('name')}")
        else:
            print(f"criando projeto {project_name} em {project_dir}...")
            client.call_tool("create_project", {"name": project_name,
                                                "location": str(project_dir)})

        print(f"importando {video.name}...")
        imported = client.call_tool("import_media", {"filePath": str(video.resolve())})
        item_id = find_key(imported, "projectItemId", "itemId", "nodeId", "id")
        if not item_id:
            items = client.call_tool("list_project_items", {})
            item_id = find_item_id_by_name(items, video.stem)
        if not item_id:
            raise MCPError("não achei o project item do vídeo importado")

        # NUNCA usar a tool create_sequence: com preset vazio ela chama
        # app.project.createNewSequence(name, "") e o Premiere abre o diálogo
        # modal "New Sequence", travando TODO o scripting até fechá-lo na mão.
        # Caminho sem diálogo: sequência a partir do clipe (herda as specs do
        # footage) -> duplicata vazia -> apaga a temporária.
        print(f"criando sequência {sequence_name} (via clipe, sem diálogo)...")
        tmp = client.call_tool("create_sequence_from_clips",
                               {"name": f"{sequence_name}_tmp",
                                "projectItemIds": [str(item_id)]})
        tmp_id = find_key(tmp, "sequenceId", "sequenceID")
        if not tmp_id:
            raise MCPError("create_sequence_from_clips não retornou sequenceId")
        seq = client.call_tool("duplicate_sequence",
                               {"sequenceId": str(tmp_id), "newName": sequence_name,
                                "clearContents": True})
        seq_id = find_key(seq, "sequenceId", "sequenceID")
        if not seq_id:
            # a resposta nem sempre traz o id; localiza pela lista (nome + vazia)
            seqs = client.call_tool("list_sequences", {})
            for s in seqs.get("sequences", []):
                if s.get("name") == sequence_name and not s.get("duration"):
                    seq_id = s.get("id")
                    break
        if not seq_id:
            raise MCPError("duplicate_sequence não retornou sequenceId")
        client.call_tool("delete_sequence", {"sequenceId": str(tmp_id)})

        clips = build_batch(cutlist, str(item_id))
        print(f"montando {len(clips)} segmentos na timeline...")
        result = client.call_tool("add_to_timeline_batch",
                                  {"sequenceId": str(seq_id), "clips": clips})
        placed = find_key(result, "placed")
        failed = find_key(result, "failed")
        status = find_key(result, "status") or "?"
        print(f"batch: status={status} placed={placed} failed={failed}")
        if status == "failure":
            raise MCPError(f"nenhum clipe foi colocado: {result}")

        client.call_tool("save_project", {})
        total = sum(s["end"] - s["start"] for s in cutlist["segments"])
        print(f"timeline '{sequence_name}' montada com {len(clips)} segmentos "
              f"(~{total:.1f}s) e projeto salvo.")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("cutlist", type=Path)
    parser.add_argument("--project-dir", type=Path,
                        default=Path.home() / "Documents")
    parser.add_argument("--project-name", default="EditorClaude_teste")
    parser.add_argument("--sequence-name", default="rough_cut")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="segundos de espera por resposta de cada tool")
    parser.add_argument("--use-open-project", action="store_true",
                        help="usa o projeto já aberto no Premiere em vez de criar um novo")
    parser.add_argument("--dry-run", action="store_true",
                        help="só mostra as chamadas planejadas, sem tocar no Premiere")
    args = parser.parse_args()

    if not args.video.exists():
        sys.exit(f"vídeo não encontrado: {args.video}")
    if not SERVER_ENTRY.exists():
        sys.exit(f"servidor MCP não compilado: {SERVER_ENTRY}\n"
                 "rode: cd vendor/Adobe_Premiere_Pro_MCP && npm install && npm run build")

    cutlist = json.loads(args.cutlist.read_text())
    if cutlist.get("version") != 1:
        sys.exit(f"versão de cut-list não suportada: {cutlist.get('version')}")

    if args.dry_run:
        clips = build_batch(cutlist, "<item_id>")
        print(f"dry-run: create_project({args.project_name!r}) -> "
              f"import_media({args.video.name!r}) -> "
              f"create_sequence({args.sequence_name!r}) -> "
              f"add_to_timeline_batch com {len(clips)} clipes:")
        for c in clips[:5]:
            print(f"  t={c['time']:8.3f}  fonte [{c['sourceInPoint']:8.3f} -> "
                  f"{c['sourceOutPoint']:8.3f}]")
        if len(clips) > 5:
            print(f"  ... +{len(clips) - 5} clipes")
        return

    render(args.video, cutlist, args.project_dir, args.project_name,
           args.sequence_name, args.timeout, args.use_open_project)


if __name__ == "__main__":
    main()
