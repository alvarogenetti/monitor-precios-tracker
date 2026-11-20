"""Escaneo headless por CLI (GitHub Actions / Programador de tareas de Windows / cron).

    python scan.py --once                  # escanea todo lo activo y termina
    python scan.py --once --target benq-ew270q
    python scan.py --once --no-alerts -v
    python scan.py --url https://www.maximus.com.ar/... --store maximus   # probar una URL suelta
    python scan.py --discover              # buscar modelos nuevos que cumplan los requisitos
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from settings import settings, setup_logging


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor de precios de monitores (AR)")
    ap.add_argument("--once", action="store_true",
                    help="escaneo único y salir (modo por defecto; se acepta por claridad en cron)")
    ap.add_argument("--target", action="append", help="limitar a uno o más target_id")
    ap.add_argument("--no-alerts", action="store_true", help="no enviar Telegram (igual se registran)")
    ap.add_argument("--url", help="probar una URL suelta sin guardar nada en la DB")
    ap.add_argument("--store", default=None, help="adaptador para --url (default: por dominio)")
    ap.add_argument("--keywords", nargs="*", default=[], help="keywords para --url de búsqueda")
    ap.add_argument("--only-local", action="store_true",
                    help='sólo los links con "ci": false (los que GitHub Actions no puede leer)')
    ap.add_argument("--meli-login", action="store_true",
                    help="login OAuth único con tu cuenta de Mercado Libre (guarda el token cifrado)")
    ap.add_argument("--meli-check", action="store_true",
                    help="prueba la API oficial de Mercado Libre con tus credenciales")
    ap.add_argument("--summary", action="store_true",
                    help="manda por Telegram el resumen diario (o lo imprime si no hay Telegram)")
    ap.add_argument("--discover", action="store_true",
                    help="descubrimiento: busca modelos que cumplan config/discovery.json")
    ap.add_argument("--json", action="store_true", help="imprimir el resumen en JSON")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    setup_logging(args.verbose)

    if args.summary:
        from services.notifier import send_telegram
        from services.summary import build_summary

        text = build_summary()
        sent = False if args.no_alerts else asyncio.run(send_telegram(text))
        print(text if not sent else "Resumen enviado por Telegram")
        return 0

    if args.meli_login or args.meli_check:
        return meli_cli(args.meli_login)

    if args.url:
        return asyncio.run(_probe(args.url, args.store, args.keywords))

    from services.tracker import fmt_ars, run_scan

    if args.discover:
        from services.discovery import STATUS_LABELS, run_discovery

        summary = asyncio.run(run_discovery("cli", send_alerts=not args.no_alerts))
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        print(f"\n{'Estado':15} {'Precio':>12}  {'Modelo':52} Tienda / notas")
        print("-" * 110)
        for r in summary["results"]:
            if r["status"] == "descartado":
                continue
            notes = ("confirmar: " + ", ".join(r["missing"])) if r["missing"] else ""
            where = r["best"]["seller"] or r["best"]["store"]
            print(f"{STATUS_LABELS[r['status']]:15} {fmt_ars(r['best']['price']):>12}  "
                  f"{r['name'][:52]:52} {where[:16]}  {notes[:40]}{'  NUEVO' if r['is_new'] else ''}")
        print(f"\n{summary['offers']} ofertas · {summary['models']} modelos · {summary['counts']}"
              f" · alertas: {summary['alerts']}{' (primera corrida: línea base)' if summary['baseline'] else ''}")
        return 1 if summary["errors"] and not summary["offers"] else 0

    summary = asyncio.run(run_scan("cli", args.target, send_alerts=not args.no_alerts,
                                   only_local=args.only_local))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print()
        print(f"{'Producto':34} {'Tienda':13} {'Cash':>12} {'Lista':>12}  Stock  Vendedor/Error")
        print("-" * 100)
        for r in summary["results"]:
            stock = {True: "si", False: "NO", None: "?"}[r["in_stock"]] if not r["error"] else "-"
            extra = r["error"] or (r.get("seller") or "")
            print(f"{r['target'][:34]:34} {r['store'][:13]:13} {fmt_ars(r['price_cash']):>12} "
                  f"{fmt_ars(r['price_list']):>12}  {stock:5}  {extra[:60]}")
        print(f"\nOK: {summary['ok']}  Errores: {summary['errors']}  Alertas: {summary['alerts']}"
              f"  (DB: {settings.db_path})")
    # Falla sólo si no se pudo scrapear nada (para que el workflow lo marque en rojo)
    return 1 if summary["results"] and summary["ok"] == 0 else 0


def meli_cli(login: bool) -> int:
    from urllib.parse import parse_qs, urlparse

    from scrapers.stores.mercadolibre import meli_client
    from services.meli_api import MeliError, best_offer

    client = meli_client()
    if client is None:
        print("Faltan ML_CLIENT_ID y ML_CLIENT_SECRET en .env (ver README > Mercado Libre).")
        return 1
    if login:
        print("1) Abrí este link, iniciá sesión en Mercado Libre y autorizá la app:\n")
        print("   " + client.login_url() + "\n")
        print(f"2) Te va a redirigir a {settings.meli_redirect_uri}?code=TG-...")
        code = ""
        while not code:
            raw = input("   Pegá acá la URL completa a la que te redirigió (o sólo el code): ")
            raw = raw.strip().strip('"').strip("'")
            code = parse_qs(urlparse(raw).query).get("code", [raw])[0].strip()
            if not code:
                print("   (llegó vacío; pegalo de nuevo con clic derecho o Ctrl+V y Enter)")
        try:
            body = client.exchange_code(code)
        except MeliError as e:
            print(f"No se pudo obtener el token: {e}")
            return 1
        print(f"\nListo: token guardado cifrado en {settings.meli_token_path} "
              f"(usuario {body.get('user_id')}).")
    try:
        client.token()
        print(f"Autenticación OK (modo: {client.mode}).")
        q = "Gigabyte GS27QA"
        prods = client.search_products(q, limit=5)
        print(f"/products/search?q={q}: {len(prods)} productos")
        for p in prods[:3]:
            items = client.product_items(p["id"])
            o = best_offer(items, seller_ok=client.seller_ok)
            price = f"$ {o['price']:,.0f}".replace(",", ".") if o else "sin publicaciones"
            print(f"  {p['id']}  {p.get('name', '')[:60]:60}  {len(items)} vendedores  {price}")
        return 0
    except MeliError as e:
        print(f"Falló la API de Mercado Libre: {e}")
        return 1


async def _probe(url: str, store: str | None, keywords: list[str]) -> int:
    from scrapers.base import BrowserSession
    from scrapers.stores import get_scraper_class
    from services.targets import Target

    cls = get_scraper_class(store, url)
    target = Target(id="probe", name="probe", target_price=1, keywords=keywords)
    async with BrowserSession(settings.headless, settings.block_stylesheets,
                              settings.page_timeout_ms) as s:
        res = await cls(s, settings.retries).scrape(url, target)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
