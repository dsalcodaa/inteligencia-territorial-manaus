"""Ponto do empreendimento (área de influência circular) e união de bairros escolhidos como área de estudo.

Raio circular NÃO é tempo/rota de deslocamento: é distância em linha reta (ver avisos nas respostas).
"""
import geopandas as gpd
from shapely.geometry import Point, mapping
from shapely.ops import unary_union

from .analysis import METRIC_CRS, load_bairros

RAIO_MIN, RAIO_MAX = 100, 20_000
MARGEM_GRAUS = 0.05


def _valida_ponto(lon: float, lat: float, bairros) -> None:
    minx, miny, maxx, maxy = bairros.total_bounds
    if not (minx - MARGEM_GRAUS <= lon <= maxx + MARGEM_GRAUS and miny - MARGEM_GRAUS <= lat <= maxy + MARGEM_GRAUS):
        raise ValueError("ponto fora da área coberta (Manaus)")


def circulo(lon: float, lat: float, raio_m: float) -> dict:
    if not RAIO_MIN <= raio_m <= RAIO_MAX:
        raise ValueError(f"raio deve estar entre {RAIO_MIN} e {RAIO_MAX} m")
    p = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(METRIC_CRS).iloc[0].buffer(raio_m, 64)
    return mapping(gpd.GeoSeries([p], crs=METRIC_CRS).to_crs(4326).iloc[0])


ANEIS_BASE = [250, 500, 1000, 2000, 3000, 5000]


def raios_aneis(raio_m: float) -> list[int]:
    """Anéis intermediários abaixo do raio escolhido, mais o próprio raio."""
    return sorted({r for r in ANEIS_BASE if r < raio_m} | {int(raio_m)})


def aneis(lon: float, lat: float, raio_m: float) -> list[dict]:
    return [{"raio_m": r, "geometry": circulo(lon, lat, r)} for r in raios_aneis(raio_m) if r >= RAIO_MIN]


def bairro_do_ponto(lon: float, lat: float, bairros=None) -> dict | None:
    """Bairro IBGE que contém o ponto, com dados oficiais por bairro; None se cair fora de todos (ex.: rio, área rural)."""
    bairros = load_bairros() if bairros is None else bairros
    hit = bairros[bairros.contains(Point(lon, lat))]
    if hit.empty:
        return None
    r = hit.iloc[0]
    v = lambda c: None if r[c] != r[c] else float(r[c])
    return {"codigo": r.CD_BAIRRO, "nome": r.NM_BAIRRO, "populacao": v("pessoas"),
            "renda_mediana": v("bairro_renda_mediana"), "renda_media": v("bairro_renda_media")}


def empreendimento(lon: float, lat: float, raio_m: float) -> dict:
    bairros = load_bairros()
    _valida_ponto(lon, lat, bairros)
    return {"geometry": circulo(lon, lat, raio_m), "raio_m": raio_m, "lon": lon, "lat": lat, "aneis": aneis(lon, lat, raio_m),
            "bairro": bairro_do_ponto(lon, lat, bairros),
            "aviso": "Área de influência = círculo em linha reta, não tempo nem rota de deslocamento."}


def uniao_bairros(codigos: list[str]) -> dict:
    if not codigos:
        raise ValueError("nenhum bairro informado")
    b = load_bairros()
    sel = b[b.CD_BAIRRO.isin(codigos)]
    desconhecidos = set(codigos) - set(sel.CD_BAIRRO)
    if desconhecidos:
        raise ValueError(f"bairros desconhecidos: {sorted(desconhecidos)}")
    return {"geometry": mapping(unary_union(list(sel.geometry))), "bairros": sorted(sel.NM_BAIRRO)}
