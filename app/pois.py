"""Estabelecimentos do OpenStreetMap (ODbL, © OpenStreetMap contributors). Uso: python -m app.pois

Cobertura do OSM é parcial e irregular: contagens são "mapeados no OSM", nunca "existentes".
Dados do Google Places NÃO entram aqui (ToS restringe armazenamento); ver app/google_places.py.
"""
import os
import time
from datetime import datetime, timezone

import geopandas as gpd
import httpx
from shapely.geometry import Point

from .analysis import DATA

OVERPASS = "https://overpass-api.de/api/interpreter"
# Overpass devolve 406 sem User-Agent; boas práticas pedem um contato (defina OVERPASS_CONTACT no ambiente, nunca no código)
UA = "plataforma-territorial-manaus/0.1" + (f" ({os.environ['OVERPASS_CONTACT']})" if os.environ.get("OVERPASS_CONTACT") else "")

# categoria → (rótulo, [(chave_osm, valor | "*")]). Ordem importa: a 1ª que casar vence; "outro_comercio" é o resíduo.
CATEGORIAS = {
    "supermercado": ("Supermercados", [("shop", "supermarket")]),
    "conveniencia": ("Conveniência e mercearias", [("shop", "convenience"), ("shop", "greengrocer")]),
    "farmacia": ("Farmácias", [("amenity", "pharmacy")]),
    "padaria": ("Padarias e confeitarias", [("shop", "bakery"), ("shop", "pastry")]),
    "restaurante": ("Restaurantes", [("amenity", "restaurant")]),
    "lanchonete": ("Lanchonetes e cafés", [("amenity", "fast_food"), ("amenity", "cafe")]),
    "bar": ("Bares", [("amenity", "bar"), ("amenity", "pub")]),
    "banco": ("Bancos", [("amenity", "bank")]),
    "combustivel": ("Postos de combustível", [("amenity", "fuel")]),
    "escola": ("Escolas e universidades", [("amenity", "school"), ("amenity", "university"), ("amenity", "college")]),
    "saude": ("Hospitais e clínicas", [("amenity", "hospital"), ("amenity", "clinic"), ("amenity", "doctors")]),
    "dentista": ("Dentistas", [("amenity", "dentist")]),
    "veterinaria": ("Veterinárias e pet shops", [("amenity", "veterinary"), ("shop", "pet")]),
    "academia": ("Academias", [("leisure", "fitness_centre")]),
    "hotel": ("Hotéis", [("tourism", "hotel")]),
    "oficina": ("Oficinas", [("shop", "car_repair")]),
    "concessionaria": ("Concessionárias", [("shop", "car")]),
    "autopecas": ("Autopeças", [("shop", "car_parts"), ("shop", "tyres")]),
    "shopping": ("Shoppings", [("shop", "mall")]),
    "material_construcao": ("Material de construção", [("shop", "doityourself"), ("shop", "hardware"), ("shop", "building_materials")]),
    "vestuario": ("Vestuário e calçados", [("shop", "clothes"), ("shop", "shoes"), ("shop", "boutique"), ("shop", "fashion_accessories")]),
    "eletronicos": ("Eletrônicos e celulares", [("shop", "electronics"), ("shop", "mobile_phone"), ("shop", "computer")]),
    "moveis": ("Móveis e decoração", [("shop", "furniture"), ("shop", "interior_decoration"), ("shop", "houseware")]),
    "beleza": ("Beleza e cuidados pessoais", [("shop", "hairdresser"), ("shop", "beauty"), ("shop", "cosmetics")]),
    "lavanderia": ("Lavanderias", [("shop", "laundry"), ("shop", "dry_cleaning")]),
    "mercado_feira": ("Feiras e mercados públicos", [("amenity", "marketplace")]),
    "outro_comercio": ("Outros comércios (shop=*)", [("shop", "*")]),
}


def _casa(tags: dict, k: str, v: str) -> bool:
    return k in tags if v == "*" else tags.get(k) == v


def _categoria(tags: dict) -> str | None:
    for cat, (_, filtros) in CATEGORIAS.items():
        if any(_casa(tags, k, v) for k, v in filtros):
            return cat
    return None


def overpass(query: str, tentativas: int = 6) -> dict:
    """POST no Overpass com User-Agent e retentativa em 429/502/503/504 (API pública, instável sob carga)."""
    for t in range(tentativas):
        resp = httpx.post(OVERPASS, data={"data": query}, headers={"User-Agent": UA}, timeout=300)
        if resp.status_code not in (429, 502, 503, 504):
            break
        time.sleep(20 * (t + 1))
    return resp.raise_for_status().json()


def bbox_manaus(margem: float = .02) -> str:
    minx, miny, maxx, maxy = gpd.read_file(DATA / "bairros_manaus.geojson").total_bounds
    return f"({miny - margem},{minx - margem},{maxy + margem},{maxx + margem})"


def ingest_pois() -> dict:
    bbox = bbox_manaus()
    sel = {(k, v) for _, f in CATEGORIAS.values() for k, v in f}
    parts = "".join(f'nwr["{k}"]{bbox};' if v == "*" else f'nwr["{k}"="{v}"]{bbox};' for k, v in sorted(sel))
    r = overpass(f"[out:json][timeout:240];({parts});out center tags;")
    rows = []
    for e in r["elements"]:
        lon, lat = (e["lon"], e["lat"]) if e["type"] == "node" else (e["center"]["lon"], e["center"]["lat"])
        cat = _categoria(e["tags"])
        if cat:
            rows.append({"categoria": cat, "nome": e["tags"].get("name"), "osm_id": f'{e["type"]}/{e["id"]}',
                         "tipo_osm": e["tags"].get("shop") or e["tags"].get("amenity") or e["tags"].get("leisure") or e["tags"].get("tourism"),
                         "geometry": Point(lon, lat)})
    g = gpd.GeoDataFrame(rows, crs=4326)
    g["fonte"] = "OpenStreetMap (ODbL)"
    g["coletado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    g.to_file(DATA / "pois_osm.gpkg", driver="GPKG")
    return g.categoria.value_counts().to_dict()


if __name__ == "__main__":
    print(ingest_pois())
