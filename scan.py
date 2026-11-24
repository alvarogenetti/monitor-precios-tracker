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

        from services.event_report import mark_sent
        from services.summary import split_message

        text = build_summary()
        parts = split_message(text)
        sent = False if args.no_alerts else all(asyncio.run(send_telegram(p)) for p in parts)
        if sent:
            mark_sent(text)       # el informe del evento se marca recién cuando llegó
        print(text if not sent else f"Resumen enviado por Telegram ({len(parts)} mensaje/s)")
        return 0

    if args.url:
        return asyncio.run(_probe(args.url, args.store, args.keywords))

    from services.tracker import fmt_ars, run_scan

    if args.discover:
        from services.discovery import STATUS_LABELS, run_discovery

        import os

        trig = "ci" if os.environ.get("GITHUB_ACTIONS") == "true" else "cli"
        summary = asyncio.run(run_discovery(trig, send_alerts=not args.no_alerts))
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

    import os

    trigger = "ci" if os.environ.get("GITHUB_ACTIONS") == "true" else "cli"
    summary = asyncio.run(run_scan(trigger, args.target, send_alerts=not args.no_alerts,
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
