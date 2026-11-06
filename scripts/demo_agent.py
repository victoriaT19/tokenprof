"""Small tool-using agent with planted waste, used to validate the detectors.

    tokenprof proxy --upstream http://localhost:11434/v1 --out wasteful.jsonl
    python scripts/demo_agent.py --mode wasteful

wasteful: the system prompt carries the current time (breaks prompt caching) and
          the tool returns a large order record where only the status matters.
fixed:    stable system prompt, time moved next to the user message, and the
          tool returns only the fields the agent needs.
"""

import argparse
import json
from datetime import datetime

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["wasteful", "fixed"], required=True)
parser.add_argument("--base", default="http://127.0.0.1:8787/v1")
parser.add_argument("--model", default="qwen2.5-cpu")
parser.add_argument("--max-steps", type=int, default=4)
args = parser.parse_args()

TOOLS = [{
    "type": "function",
    "function": {
        "name": "buscar_pedido",
        "description": "Busca um pedido pelo número",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
}]
STATUS = {101: "entregue", 102: "a caminho", 103: "cancelado"}


def full_order(order_id: int) -> dict:
    return {
        "id": order_id,
        "status": STATUS[order_id],
        "cliente": {"nome": "Cliente Exemplo", "endereco": "Rua Exemplo, 100, Recife - PE", "telefone": "(81) 90000-0000"},
        "itens": [{"sku": f"SKU-{order_id}-{i}", "descricao": f"Produto genérico número {i}", "quantidade": 1 + i % 3,
                   "preco_unitario": round(9.9 + i * 1.7, 2), "categoria": f"categoria-{i % 7}"} for i in range(25)],
        "historico": [{"evento": f"evento_{i}", "detalhe": f"registro interno de auditoria {i} do sistema logístico",
                       "timestamp": f"2026-10-30T1{i % 10}:00:00Z"} for i in range(30)],
        "metadados": {"origem": "app", "versao_api": "3.2.1", "flags": [f"flag_{i}" for i in range(20)]},
    }


def run_tool(name: str, arguments: str) -> str:
    order_id = int(json.loads(arguments or "{}").get("id", 0))
    if order_id not in STATUS:
        return json.dumps({"erro": "pedido não encontrado"})
    order = full_order(order_id)
    if args.mode == "wasteful":
        return json.dumps(order, ensure_ascii=False)
    return json.dumps({"id": order_id, "status": order["status"]}, ensure_ascii=False)


def run_agent(order_id: int) -> None:
    now = datetime.now().strftime("%H:%M:%S.%f")
    instructions = "Você é um assistente de atendimento. Use a ferramenta buscar_pedido para consultar pedidos. Responda em uma frase."
    question = f"Qual o status do pedido {order_id}?"
    if args.mode == "wasteful":
        messages = [{"role": "system", "content": f"{instructions} Horário atual: {now}."},
                    {"role": "user", "content": question}]
    else:
        messages = [{"role": "system", "content": instructions},
                    {"role": "user", "content": f"{question} (horário: {now})"}]

    run_id = f"{args.mode}-{order_id}"
    for step in range(args.max_steps):
        if args.mode == "wasteful" and step:
            messages[0]["content"] = f"{instructions} Horário atual: {datetime.now().strftime('%H:%M:%S.%f')}."
        response = httpx.post(
            f"{args.base}/chat/completions",
            json={"model": args.model, "messages": messages, "tools": TOOLS, "temperature": 0},
            headers={"X-Tokenprof-Run": run_id, "X-Tokenprof-Step": f"step-{step}"},
            timeout=300,
        ).json()
        message = response["choices"][0]["message"]
        if not message.get("tool_calls"):
            print(f"{run_id}: {message.get('content')!r} ({step + 1} calls)")
            return
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": message["tool_calls"]})
        for call in message["tool_calls"]:
            output = run_tool(call["function"]["name"], call["function"]["arguments"])
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": output})
    print(f"{run_id}: stopped after {args.max_steps} calls without a final answer")


for order in STATUS:
    run_agent(order)
