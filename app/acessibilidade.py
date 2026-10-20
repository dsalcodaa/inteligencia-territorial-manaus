"""Acessibilidade e infraestrutura da área de estudo, a partir das camadas OSM (app/osm.py).

Distâncias são em LINHA RETA a partir do centro da área, não tempo nem rota de deslocamento.
"""
import geopandas as gpd
from shapely.geometry import shape

from .analysis import DATA, METRIC_CRS

AVISO = ("Camadas do OpenStreetMap (cobertura parcial). Distâncias em linha reta a partir do centro da área, "
         "não equivalem a tempo de deslocamento. Ruas locais entram só nas métricas de km/densidade, não no mapa.")
ARTERIAIS = {"motorway", "trunk", "primary"}
_cache: dict = {}


def _camada(nome: str) -> gpd.GeoDataFrame:
    if nome not in _cache:
        _cache[nome] = gpd.read_file(DATA / f"{nome}.gpkg").to_crs(METRIC_CRS)
    return _cache[nome]


def _mais_proximo(g: gpd.GeoDataFrame, ponto) -> dict | None:
    if not len(g):
        return None
    d = g.distance(ponto)
    i = d.idxmin()
    nome = g.loc[i, "nome"]
    return {"distancia_m": round(float(d[i])), "nome": nome if isinstance(nome, str) else None}


def acessibilidade(geom: dict) -> dict:
    area = gpd.GeoSeries([shape(geom)], crs=4326).to_crs(METRIC_CRS).iloc[0]
    km2 = area.area / 1e6
    centro = area.centroid

    vias = _camada("vias_osm")
    dentro = vias.intersection(area)
    km_por_classe = (dentro.length / 1000).groupby(vias.classe.str.replace("_link", "")).sum().round(2)
    arteriais = vias[vias.classe.str.replace("_link", "").isin(ARTERIAIS)]

    locais_km = None
    if (DATA / "vias_locais_osm.gpkg").exists():
        locais_km = float(_camada("vias_locais_osm").intersection(area).length.sum() / 1000)

    infra = _camada("infra_osm")
    na_area = infra[infra.within(area)].tipo.value_counts().to_dict()
    prox = {t: _mais_proximo(infra[infra.tipo == t], centro) for t in ("ponto_onibus", "terminal_onibus", "aeroporto", "terminal_fluvial", "porto")}

    ed = _camada("edificacoes_osm")
    ed = ed[ed.intersects(area)]
    edif = [{"tipo": t, "quantidade": len(g), "area_total_m2": int(g.area_m2.sum())} for t, g in ed.groupby("tipo")]

    return {
        "aviso": AVISO, "fonte": "OpenStreetMap (ODbL), © OpenStreetMap contributors",
        "coletado_em": str(vias.coletado_em.iloc[0]),
        "area_km2": round(km2, 2),
        "vias_km": {k: float(v) for k, v in km_por_classe.items() if v > 0},
        # densidade inclui ruas locais quando carregadas; vias_km (por classe) só tem arteriais/coletoras
        "densidade_vias_km_por_km2": round(float((dentro.length.sum() / 1000 + (locais_km or 0)) / km2), 2) if km2 else None,
        "vias_locais_km": None if locais_km is None else round(locais_km, 2),
        "via_arterial_mais_proxima": _mais_proximo(arteriais, centro),
        "infra_na_area": {k: int(v) for k, v in na_area.items()},
        "mais_proximo_do_centro": prox,
        "edificacoes_nao_residenciais": sorted(edif, key=lambda x: -x["quantidade"]),
        "nota_edificacoes": "Edificações mapeadas no OSM (galpões, comerciais, industriais); NÃO são anúncios e não têm preço ou disponibilidade.",
    }
