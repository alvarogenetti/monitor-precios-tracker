"""Segmentos para ordenar los monitores seguidos (y por qué está cada uno en su lugar)."""
from __future__ import annotations

SEGMENTS = [
    ("baratos", "Opciones baratas",
     "Cumplen todo al menor precio: lo que necesitás para programar, sin pagar extras."),
    ("escalon", "Un escalón arriba",
     "Pagás algo más por algo concreto (panel más rápido, más Hz, marca con mejor postventa). "
     "Para programar no cambia mucho: conviene si el precio se acerca a los baratos."),
    ("usbc", "Con USB-C 65 W",
     "Un solo cable para la notebook (video + carga). Es lo deseable; vale hasta ~$100.000 más."),
    ("si_caen", "Gama alta: solo si caen fuerte",
     "Hoy caros para lo que aportan a programar; valen la pena con 25-30 % de descuento real."),
]
SEGMENT_KEYS = [k for k, _, _ in SEGMENTS]


def auto_segment(price: float, usb_c: bool, cheapest: float | None) -> str:
    """Segmento sugerido para un modelo nuevo (al tocar "Seguir")."""
    if usb_c:
        return "usbc"
    if not cheapest or price <= cheapest * 1.10:
        return "baratos"
    if price <= cheapest * 1.35:
        return "escalon"
    return "si_caen"
