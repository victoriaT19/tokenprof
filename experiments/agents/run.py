"""Run the 10 order tasks with one agent framework, through the tokenprof proxy.

    python run.py --framework langgraph --style full --rep 1 --results results.jsonl

Every task is one tokenprof run (X-Tokenprof-Run header), so the proxy trace can
be analyzed per task. Each framework is used with its defaults; only the model
endpoint, the tools and a one-line instruction are set.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from pathlib import Path

import store
from tasks import TASKS, is_correct

warnings.simplefilter("ignore")

INSTRUCTIONS = "Você é um assistente de atendimento de uma loja. Use as ferramentas para consultar pedidos e responda de forma curta."


def load_key(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("GEMINI_API_KEY not found in .env")


# ── Framework adapters ───────────────────────────────────────────────────────


def run_langgraph(question, style, base, key, model, headers, max_steps):
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    @tool
    def get_order(order_id: int) -> str:
        """Busca um pedido pelo número."""
        return store.get_order(order_id, style)

    @tool
    def list_customer_orders(email: str) -> str:
        """Lista os pedidos de um cliente pelo email."""
        return store.list_customer_orders(email, style)

    @tool
    def get_product(sku: str) -> str:
        """Busca um produto pelo SKU."""
        return store.get_product(sku, style)

    llm = ChatOpenAI(model=model, base_url=base, api_key=key, default_headers=headers, temperature=0, max_retries=0)
    agent = create_react_agent(llm, [get_order, list_customer_orders, get_product], prompt=INSTRUCTIONS)
    result = agent.invoke({"messages": [("user", question)]}, {"recursion_limit": 2 * max_steps + 1})
    return result["messages"][-1].content


def run_smolagents(question, style, base, key, model, headers, max_steps):
    from smolagents import OpenAIModel, ToolCallingAgent, tool

    @tool
    def get_order(order_id: int) -> str:
        """Busca um pedido pelo número.

        Args:
            order_id: número do pedido
        """
        return store.get_order(order_id, style)

    @tool
    def list_customer_orders(email: str) -> str:
        """Lista os pedidos de um cliente pelo email.

        Args:
            email: email do cliente
        """
        return store.list_customer_orders(email, style)

    @tool
    def get_product(sku: str) -> str:
        """Busca um produto pelo SKU.

        Args:
            sku: código do produto
        """
        return store.get_product(sku, style)

    llm = OpenAIModel(model_id=model, api_base=base, api_key=key,
                      client_kwargs={"default_headers": headers, "max_retries": 0}, temperature=0)
    agent = ToolCallingAgent(tools=[get_order, list_customer_orders, get_product], model=llm,
                             instructions=INSTRUCTIONS, max_steps=max_steps, verbosity_level=0)
    return str(agent.run(question))


def run_openai_agents(question, style, base, key, model, headers, max_steps):
    from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, function_tool, set_tracing_disabled
    from openai import AsyncOpenAI

    set_tracing_disabled(True)  # traces would otherwise be sent to OpenAI

    @function_tool
    def get_order(order_id: int) -> str:
        """Busca um pedido pelo número."""
        return store.get_order(order_id, style)

    @function_tool
    def list_customer_orders(email: str) -> str:
        """Lista os pedidos de um cliente pelo email."""
        return store.list_customer_orders(email, style)

    @function_tool
    def get_product(sku: str) -> str:
        """Busca um produto pelo SKU."""
        return store.get_product(sku, style)

    client = AsyncOpenAI(base_url=base, api_key=key, default_headers=headers, max_retries=0)
    agent = Agent(name="atendimento", instructions=INSTRUCTIONS,
                  model=OpenAIChatCompletionsModel(model=model, openai_client=client),
                  model_settings=ModelSettings(temperature=0),
                  tools=[get_order, list_customer_orders, get_product])
    return str(Runner.run_sync(agent, question, max_turns=max_steps).final_output)


FRAMEWORKS = {"langgraph": run_langgraph, "smolagents": run_smolagents, "openai_agents": run_openai_agents}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", choices=FRAMEWORKS, required=True)
    parser.add_argument("--style", choices=["full", "compact"], required=True)
    parser.add_argument("--rep", type=int, default=1)
    parser.add_argument("--results", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:8788/v1")
    parser.add_argument("--model", default="gemini-flash-lite-latest")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[2] / ".env"))
    parser.add_argument("--sleep", type=float, default=8.0, help="pause between tasks, to stay under free-tier rate limits")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    args = parser.parse_args()

    key = load_key(Path(args.env))
    runner = FRAMEWORKS[args.framework]
    correct = 0
    for i, task in enumerate(TASKS[: args.tasks]):
        run_id = f"{args.framework}-{args.style}-r{args.rep}-t{i}"
        headers = {"X-Tokenprof-Run": run_id}
        answer, error = None, None
        for attempt in range(3):
            try:
                answer = runner(task["question"], args.style, args.base, key, args.model, headers, args.max_steps)
                error = None
                break
            except Exception as exc:  # noqa: BLE001 - record any framework failure and move on
                error = f"{type(exc).__name__}: {exc}"[:300]
                if "429" in error or "RESOURCE_EXHAUSTED" in error:
                    time.sleep(30 * (attempt + 1))
                    headers = {"X-Tokenprof-Run": f"{run_id}-retry{attempt + 1}"}
                    continue
                break
        ok = is_correct(task, answer)
        correct += ok
        record = {"run_id": run_id, "framework": args.framework, "style": args.style, "rep": args.rep, "task": i,
                  "expected": task["expected"], "answer": answer, "correct": ok, "error": error}
        with open(args.results, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{run_id}: {'OK ' if ok else 'ERR'} {(answer or error or '')[:90]!r}", flush=True)
        time.sleep(args.sleep)
    print(f"{args.framework}/{args.style}/r{args.rep}: {correct}/{args.tasks} correct")


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
    main()
