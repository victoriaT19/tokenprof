"""Deterministic fake order API shared by every agent framework in the experiment.

Two response styles:
  full    - what a typical REST API returns: the whole record, nested objects,
            history and metadata. This is the baseline integration.
  compact - only the fields an agent needs to answer order questions. This is
            the fix tokenprof suggests for oversized tool outputs.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta

STATUSES = ["entregue", "a caminho", "cancelado", "processando"]
BRANDS = ["Aurora", "Boreal", "Cetus", "Draco", "Eridano"]
CATEGORIES = ["casa", "cozinha", "eletrônicos", "papelaria", "esporte"]
FIRST = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabi", "Heitor"]
LAST = ["Souza", "Lima", "Costa", "Rocha", "Alves", "Melo"]

_rng = random.Random(42)

PRODUCTS = {
    f"SKU-{i:03d}": {
        "sku": f"SKU-{i:03d}",
        "name": f"Produto {i:03d}",
        "brand": _rng.choice(BRANDS),
        "category": _rng.choice(CATEGORIES),
        "price": round(_rng.uniform(9.9, 499.9), 2),
        "description": f"Produto {i:03d} de uso geral, com acabamento padrão e garantia de 12 meses. " * 3,
        "specs": {"weight_g": _rng.randint(50, 5000), "dimensions_cm": [_rng.randint(5, 60) for _ in range(3)],
                  "color": _rng.choice(["preto", "branco", "azul", "verde"]), "warranty_months": 12},
        "stock": {"available": _rng.randint(0, 300), "warehouse": _rng.choice(["REC-01", "SAO-02", "BHZ-03"])},
    }
    for i in range(1, 41)
}

CUSTOMERS = {}
for i in range(8):
    name = f"{FIRST[i]} {LAST[i % len(LAST)]}"
    email = f"{FIRST[i].lower().replace('á', 'a')}.{LAST[i % len(LAST)].lower()}@exemplo.com"
    CUSTOMERS[email] = {"name": name, "email": email, "phone": f"(81) 9{_rng.randint(1000, 9999)}-{_rng.randint(1000, 9999)}",
                        "address": {"street": f"Rua Exemplo {_rng.randint(1, 999)}", "city": "Recife", "state": "PE",
                                    "zip": f"5{_rng.randint(1000, 9999)}-000"},
                        "loyalty": {"tier": _rng.choice(["bronze", "prata", "ouro"]), "points": _rng.randint(0, 5000)}}

ORDERS = {}
_emails = list(CUSTOMERS)
for i in range(1001, 1041):
    email = _emails[(i - 1001) % len(_emails)]
    status = STATUSES[_rng.randrange(len(STATUSES))]
    created = date(2026, 9, 1) + timedelta(days=_rng.randint(0, 50))
    items = []
    for sku in _rng.sample(sorted(PRODUCTS), _rng.randint(1, 4)):
        product = PRODUCTS[sku]
        items.append({"sku": sku, "quantity": _rng.randint(1, 3), "unit_price": product["price"], "product": product})
    total = round(sum(it["quantity"] * it["unit_price"] for it in items), 2)
    events = [{"type": "criado", "date": created.isoformat(), "note": "pedido registrado no sistema de vendas"}]
    if status in ("a caminho", "entregue"):
        events.append({"type": "enviado", "date": (created + timedelta(days=2)).isoformat(), "note": "coletado pela transportadora"})
    if status == "entregue":
        events.append({"type": "entregue", "date": (created + timedelta(days=5)).isoformat(), "note": "entregue ao destinatário"})
    if status == "cancelado":
        events.append({"type": "cancelado", "date": (created + timedelta(days=1)).isoformat(), "note": "cancelado a pedido do cliente"})
    ORDERS[i] = {"id": i, "status": status, "created_at": created.isoformat(), "customer": CUSTOMERS[email],
                 "items": items, "total": total, "currency": "BRL",
                 "payment": {"method": _rng.choice(["pix", "cartão", "boleto"]), "installments": _rng.randint(1, 6),
                             "transaction_id": f"TX{_rng.randint(10**9, 10**10 - 1)}"},
                 "shipping": {"carrier": _rng.choice(["Correios", "Loggi", "Jadlog"]), "fee": round(_rng.uniform(0, 30), 2),
                              "tracking_code": f"BR{_rng.randint(10**8, 10**9 - 1)}PE"},
                 "events": events,
                 "metadata": {"channel": _rng.choice(["app", "site"]), "api_version": "3.2.1",
                              "flags": [f"flag_{k}" for k in range(8)]}}


def _compact_order(order: dict) -> dict:
    delivered = next((e["date"] for e in order["events"] if e["type"] == "entregue"), None)
    return {"id": order["id"], "status": order["status"], "customer": order["customer"]["name"],
            "total": order["total"], "delivered_at": delivered,
            "items": [{"sku": it["sku"], "name": it["product"]["name"], "quantity": it["quantity"]} for it in order["items"]]}


def get_order(order_id: int, style: str) -> str:
    order = ORDERS.get(int(order_id))
    if order is None:
        return json.dumps({"error": f"pedido {order_id} não encontrado"}, ensure_ascii=False)
    return json.dumps(order if style == "full" else _compact_order(order), ensure_ascii=False)


def list_customer_orders(email: str, style: str) -> str:
    orders = [o for o in ORDERS.values() if o["customer"]["email"] == email.strip().lower()]
    if not orders:
        return json.dumps({"error": f"cliente {email} não encontrado"}, ensure_ascii=False)
    if style == "full":
        return json.dumps({"customer": orders[0]["customer"], "orders": orders, "count": len(orders)}, ensure_ascii=False)
    return json.dumps({"customer": orders[0]["customer"]["name"],
                       "orders": [{"id": o["id"], "status": o["status"], "total": o["total"]} for o in orders]},
                      ensure_ascii=False)


def get_product(sku: str, style: str) -> str:
    product = PRODUCTS.get(sku.strip().upper())
    if product is None:
        return json.dumps({"error": f"produto {sku} não encontrado"}, ensure_ascii=False)
    if style == "full":
        return json.dumps(product, ensure_ascii=False)
    return json.dumps({k: product[k] for k in ("sku", "name", "brand", "price")}, ensure_ascii=False)
