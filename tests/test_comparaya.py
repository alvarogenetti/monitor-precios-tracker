"""ComparaYa: sólo fichas /p/ (robots.txt permite), ofertas nuevas, ML + tiendas que no leemos."""
from pathlib import Path

from services import comparaya as cy

FIX = Path(__file__).parent / "fixtures"


def page(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_new_offers_with_ml():
    offers = cy.parse(page("comparaya_vg27aql3a.html"))
    assert [o["shop"] for o in offers] == ["Portal Store", "Mercado Libre"]
    ml = offers[1]
    assert ml["price"] == 640000 and ml["list"] == 1197039 and "/p/MLA43959825" in ml["url"] and cy.is_ml(ml)


def test_parse_international_flag():
    offers = cy.parse(page("comparaya_xg27aqngv.html"))
    assert offers[0]["shop"] == "Fravega" and offers[0]["intl"] and not offers[1]["intl"]


def test_slug_candidates():
    assert cy.slug_candidates("ASUS", "VG27AQL3A", "VG27AQL3A") == ["monitor-asus-vg27aql3a-27", "monitor-asus-vg27aql3a"]
    assert "monitor-arkham-ark27210-27" in cy.slug_candidates("ARKHAM", "ARK27210QI8", "ARK27210")
    assert cy.slug_candidates(None, "X", "X") == []


class FakeClient:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def __enter__(self): return self
    def __exit__(self, *a): pass

    def get(self, url):
        self.calls.append(url)
        slug = url.rsplit("/", 1)[1]
        return type("R", (), {"status_code": 200 if slug in self.pages else 404, "text": self.pages.get(slug, "")})


def test_collect_keeps_ml_and_unknown_stores_only(monkeypatch):
    fake = FakeClient({"monitor-asus-vg27aql3a-27": page("comparaya_vg27aql3a.html")})
    monkeypatch.setattr(cy.httpx, "Client", lambda **k: fake)
    monkeypatch.setattr(cy, "PAUSE_S", 0)
    models = [{"key": "VG27AQL3A", "brand": "ASUS", "search": "VG27AQL3A"}]
    got = cy.collect(None, models, {"portalstore.com.ar"})          # Portal Store ya se lee directo
    assert [o["seller"] for o in got] == ["Mercado Libre (vía ComparaYa)"]
    assert cy.collect(None, models, set())[0]["seller"] == "Portal Store (vía ComparaYa)"


def test_collect_skips_other_versions(monkeypatch):
    fake = FakeClient({"monitor-asus-vg27aql-27": page("comparaya_vg27aql3a.html")})
    monkeypatch.setattr(cy.httpx, "Client", lambda **k: fake)
    monkeypatch.setattr(cy, "PAUSE_S", 0)
    # La ficha existe pero sus ofertas son de otro código (VG27AQL3A ≠ VG27AQL5A): no se toman
    got = cy.collect(None, [{"key": "VG27AQL5A", "brand": "ASUS", "search": "VG27AQL5A"}], set(),
                     manual={"VG27AQL5A": "monitor-asus-vg27aql-27"})
    assert got == []


def test_known_shop_by_name():
    own = {cy._name(x) for x in ["Amonpul Team", "XT-PC", "MyM", "Compufan"]}
    assert cy.known_shop("Amonpul", own) and cy.known_shop("XT-PC", own) and cy.known_shop("MyM Computación", own)
    assert not cy.known_shop("Portal Store", own) and not cy.known_shop("Gaming City", own)
