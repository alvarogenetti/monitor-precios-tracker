"""Qué tiendas se revisan, cómo y cada cuánto (para la pestaña Info del dashboard)."""
from __future__ import annotations

STORES = [
    {"group": "Seguimiento cada ~3 h (y cada hora en eventos)", "items": [
        ("Compra Gamer", "Catálogo completo que descarga la propia página (precio especial y de lista)", "GitHub"),
        ("HardGamers", "Comparador: ~41 tiendas (Maximus, Mexx, Full H4rd, Gezatek, TryHardware, Slot One, Logg, "
                       "Katech, SilverHard, Compufan, Hyper Gaming, MyM, XT-PC, Amonpul…)", "GitHub"),
        ("Mercado Libre", "Su API nos bloqueó el 23/11/2026. Desde el 24/11 el precio llega una vez por día "
                          "vía ComparaYa (afiliado de ML); además links «Ver en ML» y carga manual «Lo vi a $» "
                          "(vale 3 días)", "GitHub + a mano"),
        ("Electro (VTEX)", "On City, Cetrogar, Carrefour, Pardo, Coppel, Naldo, Jumbo, Samsung Shop, "
                           "Diamond Computación y Provincia Compras: la más barata entre todas", "GitHub"),
        ("Frávega", "API de su buscador (incluye vendedores del marketplace)", "Tu PC"),
        ("Venex", "Ficha directa (GS27QA)", "Tu PC"),
        ("Maximus", "Ficha directa (MSI 275QF)", "GitHub"),
    ]},
    {"group": "Descubrimiento una vez por día, cada ~3 h en eventos (cualquier 27\" QHD)", "items": [
        ("Compra Gamer", "Catálogo completo", "GitHub"),
        ("HardGamers", "Búsquedas: monitor 27 qhd / 2k / 1440 / wqhd / ips 180hz", "GitHub"),
        ("On City, Pardo, Carrefour, Cetrogar, Coppel, Naldo", "Buscador VTEX: monitor 27 qhd", "GitHub"),
        ("Samsung Shop", "Buscador VTEX: monitor 27", "GitHub"),
        ("Dell Argentina", "Categoría de monitores (desde GitHub sólo la primera página)", "GitHub"),
        ("Megatone", "Categoría de monitores (primeros 20)", "GitHub"),
        ("Nickhard", "Buscador Tiendanube: monitor 27 (precio por transferencia)", "GitHub"),
        ("Mallweb", "Categoría de monitores (precio en efectivo/transferencia)", "GitHub"),
        ("Comeros, ISInet, Aura Gamer, Espaciotek, Zonetech, Hardcore, DeCaba",
         "WooCommerce: API pública de la tienda (búsqueda \"monitor\")", "GitHub"),
        ("Shopgamer, Dualkey", "Buscador Tiendanube (precio por transferencia)", "GitHub"),
        ("Electrotics, Gerbio, PC Registrada", "Buscador Qloud (catálogo Microglobal)", "GitHub"),
        ("Armytech", "Buscador PrestaShop", "GitHub"),
        ("Otecno", "Buscador TiendaNegocio (precio por transferencia)", "GitHub"),
        ("Red Sur, Ultra Computación, City Gadgets, Nova Online, Clanco, 710 Technology, PC Store, "
         "Support Oficial, Best Informática, Hunter Gaming", "Buscador Qloud", "GitHub"),
        ("NG Technologies, West Solution", "Buscador Tiendanube", "GitHub"),
        ("HardLoots, Astro Hard", "WooCommerce: API pública", "GitHub"),
        ("Libre Opción", "Marketplace (Gears Store, STORE GS, BsAsPC...): su API de búsqueda", "GitHub"),
        ("Seguimiento Gamer", "Comparador de 23 tiendas (su listado público de monitores): respaldo si "
                              "falla el lector propio de una tienda, y link al historial de cada producto", "GitHub"),
        ("ComparaYa", "Comparador de 251 tiendas: de las fichas de los modelos que cumplen se toman Mercado Libre "
                      "y las tiendas que no leemos directo (sólo ofertas nuevas del código exacto)", "GitHub"),
        ("Diamond Computación, Provincia Compras", "Buscador VTEX (Provincia Compras es marketplace)", "GitHub"),
        ("Frávega", "Buscador: monitor 27 qhd / 2k", "Tu PC"),
    ]},
    {"group": "Evaluadas y descartadas", "items": [
        ("Musimundo", "Sitio en mantenimiento; redirige a On City (que ya está)", "—"),
        ("Garbarino / Compumundo", "El dominio no responde", "—"),
        ("ASUS Store", "Pide captcha (no se evade)", "—"),
        ("LG Argentina", "No vende online", "—"),
        ("Lenovo / HP", "Sólo con navegador y casi sin QHD 27\" en stock", "—"),
        ("Amazon / Tiendamia", "Importación: demora, envío caro y garantía difícil; no se suman", "—"),
        ("Invid, Elit, Grupo Núcleo", "Mayoristas: precios sólo con usuario", "—"),
        ("Tienda BNA", "Protegida contra bots (Cloudflare): no se lee. En la fila de ML de cada seguido, «En Tienda BNA a $» para cargar a mano", "A mano"),
        ("Coto, Bidcom", "Se revisaron con navegador: no venden 27\" QHD de marca conocida (Bidcom sólo Gadnic 24/34\")", "—"),
        ("Noblex, Bangho, Tienda Ciudad", "Arman la página con JavaScript (sin navegador no hay productos)", "—"),
        ("Casa del Audio, Rodo, Sodimac, Easy, Castillo, Novogar...", "Se revisaron: no venden 27\" QHD", "—"),
        ("Compel, Fefotec, Incot, BitHard, Vccit, Ar-Hard, Integrados Argentinos, Authogar",
         "Se revisaron: no venden 27\" QHD", "—"),
        ("BuscaHard, Precios GG, Historial de Precios, Precialo", "Comparadores revisados: sus tiendas "
         "útiles se leen directo (BuscaHard bloquea bots de IA en robots.txt; Precios GG está vacío; Historial "
         "cubre supermercados; Precialo es casi todo Mercado Libre, ya cubierto vía ComparaYa)", "—"),
        ("MercadoTrack, RadarLibre, Jina/Apify/Octoparse", "Leer ML a través de terceros: va contra la cláusula 12 de "
         "ML (uso automatizado). MejoresCompras sólo como link «Historial»", "—"),
    ]},
]
