"""Ten order questions whose answers are computed from the fake store, plus a checker."""

from __future__ import annotations

import re

from store import CUSTOMERS, ORDERS, PRODUCTS

_emails = sorted(CUSTOMERS)


def _orders_of(email: str) -> list[dict]:
    return [o for o in ORDERS.values() if o["customer"]["email"] == email]


def _delivered_date(order: dict) -> str:
    return next(e["date"] for e in order["events"] if e["type"] == "entregue")


def _count(email: str, status: str) -> int:
    return sum(o["status"] == status for o in _orders_of(email))


# Customers picked so that no expected answer is zero (a "0" is too easy to match by accident).
_delivered = [o for o in ORDERS.values() if o["status"] == "entregue"]
_c1 = max(_emails, key=lambda e: _count(e, "entregue"))
_c2 = max((e for e in _emails if e != _c1), key=lambda e: _count(e, "cancelado"))
_c3 = _emails[6]

TASKS = [
    {"question": "Qual é o status do pedido 1007?", "expected": ORDERS[1007]["status"], "kind": "text"},
    {"question": "Quantas unidades de produtos, somando as quantidades, tem o pedido 1012?",
     "expected": sum(it["quantity"] for it in ORDERS[1012]["items"]), "kind": "number"},
    {"question": "Qual é o valor total do pedido 1021, em reais?", "expected": ORDERS[1021]["total"], "kind": "number"},
    {"question": "Qual é o nome do cliente que fez o pedido 1033?", "expected": ORDERS[1033]["customer"]["name"], "kind": "text"},
    {"question": f"Quantos pedidos o cliente {_c1} tem?", "expected": len(_orders_of(_c1)), "kind": "number"},
    {"question": f"Quantos pedidos do cliente {_c2} foram cancelados?",
     "expected": sum(o["status"] == "cancelado" for o in _orders_of(_c2)), "kind": "number"},
    {"question": f"Qual é o número do pedido mais caro do cliente {_c3}?",
     "expected": max(_orders_of(_c3), key=lambda o: o["total"])["id"], "kind": "number"},
    {"question": "Qual é a marca do primeiro item do pedido 1018?",
     "expected": PRODUCTS[ORDERS[1018]["items"][0]["sku"]]["brand"], "kind": "text"},
    {"question": f"Quanto o cliente {_c1} gastou, em reais, somando só os pedidos entregues?",
     "expected": round(sum(o["total"] for o in _orders_of(_c1) if o["status"] == "entregue"), 2), "kind": "number"},
    {"question": f"Em que data (AAAA-MM-DD) o pedido {_delivered[1]['id']} foi entregue?",
     "expected": _delivered_date(_delivered[1]), "kind": "text"},
]


def _numbers(text: str) -> list[float]:
    values = []
    for raw in re.findall(r"\d[\d.,]*", text):
        raw = raw.rstrip(".,")
        if "," in raw:  # Brazilian format: 1.234,56
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        try:
            values.append(float(raw))
        except ValueError:
            pass
    return values


def is_correct(task: dict, answer: str | None) -> bool:
    if not answer:
        return False
    if task["kind"] == "number":
        return any(abs(v - float(task["expected"])) < 0.011 for v in _numbers(answer))
    return str(task["expected"]).lower() in answer.lower()
