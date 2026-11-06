"""End-to-end check of the proxy against a real OpenAI-compatible server (e.g. Ollama).

Start the proxy first, then run:

    tokenprof proxy --upstream http://localhost:11434/v1 --out traces.jsonl
    python scripts/e2e_ollama.py traces.jsonl --model qwen2.5-cpu

Makes three calls through the proxy (plain, streaming, streaming with a tool)
and prints the trace records they produced.
"""

import argparse
import json
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("trace_path")
parser.add_argument("--base", default="http://127.0.0.1:8787/v1")
parser.add_argument("--model", default="qwen2.5-cpu")
args = parser.parse_args()

headers = {"X-Tokenprof-Run": "e2e-1"}

for _ in range(30):
    try:
        httpx.get(f"{args.base}/models", timeout=2)
        break
    except httpx.HTTPError:
        time.sleep(0.5)

msgs = [{"role": "user", "content": "Responda em uma frase: qual a capital de Pernambuco?"}]

r = httpx.post(f"{args.base}/chat/completions", json={"model": args.model, "messages": msgs},
               headers={**headers, "X-Tokenprof-Step": "nao-stream"}, timeout=120)
print("nao-stream:", r.status_code)

with httpx.stream("POST", f"{args.base}/chat/completions",
                  json={"model": args.model, "messages": msgs, "stream": True},
                  headers={**headers, "X-Tokenprof-Step": "stream"}, timeout=120) as s:
    for _ in s.iter_lines():
        pass
print("stream:", s.status_code)

tools = [{"type": "function", "function": {
    "name": "clima", "description": "Previsão do tempo de uma cidade",
    "parameters": {"type": "object", "properties": {"cidade": {"type": "string"}}, "required": ["cidade"]}}}]
r = httpx.post(f"{args.base}/chat/completions",
               json={"model": args.model, "stream": True, "tools": tools,
                     "messages": [{"role": "user", "content": "Como está o tempo em Recife?"}]},
               headers={**headers, "X-Tokenprof-Step": "tool-stream"}, timeout=120)
print("tool-stream:", r.status_code)

print("\n--- trace records ---")
with open(args.trace_path, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        fields = ("step", "stream", "status", "latency_ms", "ttft_ms", "usage", "error")
        print(json.dumps({k: rec[k] for k in fields}, ensure_ascii=False))
        print("   response:", json.dumps(rec["response"], ensure_ascii=False)[:200])
