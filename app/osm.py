"""Camadas OSM de rede viária, transporte/infraestrutura e edificações não residenciais. Uso: python -m app.osm

© OpenStreetMap contributors, ODbL. Cobertura parcial. Edificações aqui NÃO são anúncios: o OSM não tem preço nem
disponibilidade; servem só para localizar galpões/imóveis comerciais e industriais existentes.
"""
import time
from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from .analysis import DATA
from .pois import bbox_manaus, overpass

VIAS = "motorway|trunk|primary|secondary|tertiary"
EDIF = "warehouse|industrial|commercial|retail|office|supermarket|factory"


def _coords(e):
    return [(p["lon"], p["lat"]) for p in e["geometry"]]


def _salva(rows, nome):
    g = gpd.GeoDataFrame(rows, crs=4326)
    g["fonte"], g["coletado_em"] = "OpenStreetMap (ODbL)", datetime.now(timezone.utc).isoformat(timespec="seconds")
    g.to_file(DATA / f"{nome}.gpkg", driver="GPKG")
    return g


def ingest_vias() -> dict:
    b = bbox_manaus()
    r = overpass(f'[out:json][timeout:240];way["highway"~"^({VIAS})(_link)?$"]{b};out geom tags;')
    rows = [{"classe": e["tags"]["highway"], "nome": e["tags"].get("name"), "ref": e["tags"].get("ref"),
             "pista_dupla": e["tags"].get("oneway") == "yes", "geometry": LineString(_coords(e))}
            for e in r["elements"] if e["type"] == "way" and len(e.get("geometry", [])) > 1]
    return _salva(rows, "vias_osm").classe.value_counts().to_dict()


def ingest_vias_locais() -> dict:
    """Ruas locais (residential/unclassified/living_street). Só para métricas (km, densidade); não vão ao mapa (volume)."""
    r = overpass(f'[out:json][timeout:300];way["highway"~"^(residential|unclassified|living_street)$"]{bbox_manaus()};out geom tags;')
    rows = [{"classe": e["tags"]["highway"], "nome": e["tags"].get("name"), "geometry": LineString(_coords(e))}
            for e in r["elements"] if e["type"] == "way" and len(e.get("geometry", [])) > 1]
    return _salva(rows, "vias_locais_osm").classe.value_counts().to_dict()


def ingest_infra() -> dict:
    b = bbox_manaus()
    q = (f'[out:json][timeout:240];(node["highway"="bus_stop"]{b};nwr["amenity"="bus_station"]{b};'
         f'nwr["aeroway"~"^(aerodrome|terminal|heliport)$"]{b};nwr["amenity"="ferry_terminal"]{b};'
         f'nwr["harbour"="yes"]{b};nwr["landuse"="port"]{b};nwr["man_made"="pier"]{b};nwr["waterway"="dock"]{b};'
         f'nwr["office"="government"]{b};);out center tags;')
    rows = []
    for e in overpass(q)["elements"]:
        t = e["tags"]
        lon, lat = (e["lon"], e["lat"]) if e["type"] == "node" else (e["center"]["lon"], e["center"]["lat"])
        tipo = ("ponto_onibus" if t.get("highway") == "bus_stop" else "terminal_onibus" if t.get("amenity") == "bus_station"
                else ("aeroporto" if t.get("iata") and t.get("aerodrome:type") in ("international", "public", "regional") else "aerodromo")
                if t.get("aeroway") == "aerodrome"  # civil com IATA (ex.: MAO); base aérea/pequenos campos ficam como "aerodromo"
                else "terminal_aeroporto" if "aeroway" in t else "terminal_fluvial" if t.get("amenity") == "ferry_terminal"
                else "porto" if (t.get("harbour") == "yes" or t.get("landuse") == "port" or "man_made" in t or "waterway" in t)
                else "orgao_publico")
        rows.append({"tipo": tipo, "nome": t.get("name"), "osm_id": f'{e["type"]}/{e["id"]}', "geometry": Point(lon, lat)})
    return _salva(rows, "infra_osm").tipo.value_counts().to_dict()


def ingest_edificacoes() -> dict:
    """Galpões, indústrias e imóveis comerciais mapeados (polígonos fechados), com área em m²."""
    b = bbox_manaus()
    q = (f'[out:json][timeout:240];(way["building"~"^({EDIF})$"]{b};way["landuse"~"^(industrial|commercial|retail)$"]{b};);'
         f'out geom tags;')
    rows = []
    for e in overpass(q)["elements"]:
        c = _coords(e) if e["type"] == "way" and e.get("geometry") else []
        if len(c) < 4 or c[0] != c[-1]:
            continue
        t = e["tags"]
        tipo = t["building"] if t.get("building") in EDIF.split("|") else f'terreno_{t["landuse"]}' if "landuse" in t else None
        if tipo is None:
            continue
        rows.append({"tipo": tipo, "nome": t.get("name"),
                     "osm_id": f'way/{e["id"]}', "geometry": Polygon(c)})
    g = gpd.GeoDataFrame(rows, crs=4326)
    g["area_m2"] = g.to_crs(31980).area.round(0)
    _salva(g.drop(columns="geometry").assign(geometry=g.geometry), "edificacoes_osm")
    return g.tipo.value_counts().to_dict()


if __name__ == "__main__":
    for f in (ingest_vias, ingest_infra, ingest_edificacoes):
        print(f.__name__, f())
        time.sleep(10)  # cortesia com a API pública
