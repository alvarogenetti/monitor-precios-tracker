"""Qué tiendas se revisan, cómo y cada cuánto (para la pestaña Info del dashboard)."""
from __future__ import annotations

STORES = [
    {"group": "Seguimiento cada ~3 h (y cada hora en eventos)", "items": [
        ("Compra Gamer", "Catálogo completo que descarga la propia página (precio especial y de lista)", "GitHub"),
        ("HardGamers", "Comparador: ~41 tiendas (Maximus, Mexx, Full H4rd, Gezatek, TryHardware, Slot One, Logg, "
                       "Katech, SilverHard, Compufan, Hyper Gaming, MyM, XT-PC, Amonpul…)", "GitHub"),
        ("Mercado Libre", "API oficial: publicación nueva más barata de vendedores con reputación", "GitHub"),
        ("Electro (VTEX)", "On City, Cetrogar, Carrefour, Pardo, Coppel, Naldo, Jumbo y Samsung Shop: "
                           "la más barata entre todas", "GitHub"),
        ("Frávega", "API de su buscador (incluye vendedores del marketplace)", "Tu PC"),
        ("Venex", "Ficha directa (GS27QA)", "Tu PC"),
        ("Maximus", "Ficha directa (MSI 275QF)", "GitHub"),
    ]},
    {"group": "Descubrimiento una vez por día (cualquier 27\" QHD)", "items": [
        ("Compra Gamer", "Catálogo completo", "GitHub"),
        ("HardGamers", "Búsquedas: monitor 27 qhd / 2k / 1440 / wqhd / ips 180hz", "GitHub"),
        ("On City, Pardo, Carrefour, Cetrogar, Coppel, Naldo", "Buscador VTEX: monitor 27 qhd", "GitHub"),
        ("Samsung Shop", "Buscador VTEX: monitor 27", "GitHub"),
        ("Dell Argentina", "Categoría de monitores (desde GitHub sólo la primera página)", "GitHub"),
        ("Megatone", "Categoría de monitores (primeros 20)", "GitHub"),
        ("Nickhard", "Buscador Tiendanube: monitor 27 (precio por transferencia)", "GitHub"),
        ("Mallweb", "Categoría de monitores (precio en efectivo/transferencia)", "GitHub"),
        ("Frávega", "Buscador: monitor 27 qhd / 2k", "Tu PC"),
    ]},
    {"group": "Evaluadas y descartadas", "items": [
        ("Musimundo", "Sitio en mantenimiento; redirige a On City (que ya está)", "—"),
        ("Garbarino / Compumundo", "El dominio no responde", "—"),
        ("ASUS Store", "Pide captcha (no se evade)", "—"),
        ("LG Argentina", "No vende online", "—"),
        ("Lenovo / HP", "Sólo con navegador y casi sin QHD 27\" en stock", "—"),
        ("Amazon / Tiendamia", "Importación: demora, envío caro y garantía difícil; no se suman", "—"),
    ]},
]
