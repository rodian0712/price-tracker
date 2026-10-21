#!/usr/bin/env python3
"""Daily price tracker for product pages that expose a machine-readable price."""
from __future__ import annotations

import csv
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
PRODUCTS_FILE = ROOT / "products.json"
HISTORY_FILE = ROOT / "prices.csv"
TZ = ZoneInfo("America/Santiago")
CSV_FIELDS = [
    "checked_at_chile", "product_id", "product_name", "variant",
    "store", "price_clp", "currency", "availability", "url", "status"
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PersonalPriceTracker/1.0; "
        "+https://github.com/rodian0712/price-tracker)"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
}


def parse_price(value):
    """Convert a machine-readable price to a numeric amount."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if not value:
        return None
    # JSON-LD prices are normally numeric strings; don't parse arbitrary page text here.
    cleaned = re.sub(r"[^0-9,.]", "", value)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # Chilean display often uses 34.990, while machine values use 34990 or 34.99.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Decimal comma when there are 1-2 digits after it; otherwise thousands separator.
        tail = cleaned.rsplit(",", 1)[-1]
        cleaned = cleaned.replace(",", ".") if len(tail) <= 2 else cleaned.replace(",", "")
    elif "." in cleaned:
        tail = cleaned.rsplit(".", 1)[-1]
        if len(tail) == 3:
            cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def walk_jsonld(node):
    if isinstance(node, dict):
        yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from walk_jsonld(item)
    elif isinstance(node, list):
        for item in node:
            yield from walk_jsonld(item)


def find_product_price(soup):
    """Prefer structured product offers and price metadata over arbitrary page text."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in walk_jsonld(data):
            types = item.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if not any(t.lower() == "product" for t in types if isinstance(t, str)):
                continue
            offers = item.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            for offer in offers if isinstance(offers, list) else []:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price")
                if price is None and isinstance(offer.get("priceSpecification"), dict):
                    price = offer["priceSpecification"].get("price")
                parsed = parse_price(price)
                currency = offer.get("priceCurrency", "CLP")
                if parsed is not None:
                    availability = str(offer.get("availability", "unknown")).rsplit("/", 1)[-1]
                    return parsed, currency, availability

    meta_selectors = [
        ('meta[property="product:price:amount"]', "content"),
        ('meta[property="og:price:amount"]', "content"),
        ('meta[itemprop="price"]', "content"),
    ]
    for selector, attr in meta_selectors:
        tag = soup.select_one(selector)
        if tag:
            parsed = parse_price(tag.get(attr))
            if parsed is not None:
                currency_tag = (
                    soup.select_one('meta[property="product:price:currency"]')
                    or soup.select_one('meta[property="og:price:currency"]')
                )
                currency = currency_tag.get("content", "CLP") if currency_tag else "CLP"
                return parsed, currency, "unknown"
    return None, "CLP", "unknown"


def fetch_product(product):
    url = product["url"].strip()
    if not url or "PEGA_AQUI" in url:
        raise ValueError("Falta configurar una URL real del producto en products.json")
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    price, currency, availability = find_product_price(soup)

    # Do not silently convert a foreign currency into CLP. Record source currency as provided.
    if price is None:
        return {
            "price": "", "currency": currency, "availability": availability,
            "status": "NO_PRICE_FOUND (página bloqueada o precio no detectable)"
        }
    return {
        "price": round(price, 2), "currency": currency,
        "availability": availability, "status": "OK"
    }


def append_history(rows):
    exists = HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists or HISTORY_FILE.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(rows)


def send_email(subject, body):
    required = ["MAIL_USERNAME", "MAIL_TO", "GMAIL_APP_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print("Correo no enviado: faltan secrets " + ", ".join(missing))
        return False

    username = os.environ["MAIL_USERNAME"]
    recipient = os.environ["MAIL_TO"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = recipient
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
        server.login(username, password)
        server.send_message(message)
    print(f"Correo enviado a {recipient}")
    return True


def main():
    try:
        products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"No se pudo leer products.json: {exc}", file=sys.stderr)
        return 1

    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    rows = []
    report = [
        f"Price Tracker — {datetime.now(TZ).strftime('%d-%m-%Y %H:%M')} (hora de Chile)",
        "",
        "Precios detectados hoy:",
        ""
    ]

    for product in products:
        if not product.get("enabled", True):
            continue
        try:
            result = fetch_product(product)
        except Exception as exc:
            result = {
                "price": "", "currency": "CLP", "availability": "unknown",
                "status": f"ERROR: {type(exc).__name__}: {exc}"
            }

        row = {
            "checked_at_chile": checked_at,
            "product_id": product.get("id", ""),
            "product_name": product.get("name", ""),
            "variant": product.get("variant", ""),
            "store": product.get("store", ""),
            "price_clp": result["price"] if result["currency"] == "CLP" else "",
            "currency": result["currency"],
            "availability": result["availability"],
            "url": product.get("url", ""),
            "status": result["status"],
        }
        rows.append(row)

        if result["price"] != "":
            formatted = f"{result['price']:,.0f}".replace(",", ".")
            price_text = f"{result['currency']} ${formatted}" if result["currency"] == "CLP" else f"{result['currency']} {result['price']}"
            report.append(f"- {product.get('name')} — {product.get('variant', 'variante no indicada')}: {price_text}")
        else:
            report.append(f"- {product.get('name')} — {product.get('variant', '')}: precio no detectado.")
        report.append(f"  Tienda: {product.get('store', '')} | Estado: {result['status']}")
        report.append(f"  URL: {product.get('url', '')}")
        report.append("")

    append_history(rows)
    report += [
        "Nota: el precio depende de lo que publique la página y puede no incluir despacho.",
        "Si una página no expone el precio de forma legible para el tracker, revisa el estado en el reporte."
    ]
    body = "\n".join(report)
    print(body)

    try:
        send_email(
            f"Price Tracker — {datetime.now(TZ).strftime('%d-%m-%Y')}",
            body
        )
    except Exception as exc:
        print(f"Error al enviar correo: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
