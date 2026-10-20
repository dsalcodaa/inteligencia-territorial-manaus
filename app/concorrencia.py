"""Análise de concorrência: estabelecimentos mapeados no OSM dentro da área de estudo."""
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, shape

from .analysis import DATA, METRIC_CRS, load_bairros, summarize
from .pois import CATEGORIAS

AVISO = ("Contagem de estabelecimentos MAPEADOS no OpenStreetMap, base voluntária com cobertura parcial e irregular: "
         "subestima a oferta real e não distingue concorrente direto de indireto. Valide em campo antes de decidir.")
_cache: dict = {}


def load_pois() -> gpd.GeoDataFrame:
    if "p" not in _cache:
        _cache["p"] = gpd.read_file(DATA / "pois_osm.gpkg").to_crs(METRIC_CRS)
    return _cache["p"]


ANEIS_M = [250, 500, 1000, 2000, 3000, 5000]


def _do_ponto(todos, lon: float, lat: float) -> dict:
    """Concorrentes a partir do ponto do empreendimento: contagem acumulada por raio e os 5 mais próximos (linha reta)."""
    p = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(METRIC_CRS).iloc[0]
    d = todos.distance(p).sort_values()
    return {"aneis": [{"raio_m": r, "estabelecimentos": int((d <= r).sum())} for r in ANEIS_M],
            "mais_proximos": [{"nome": todos.loc[i, "nome"] if isinstance(todos.loc[i, "nome"], str) else None, "distancia_m": round(float(x))}
                              for i, x in d.head(5).items()]}


def concorrencia(geom: dict, categoria: str, ponto: tuple[float, float] | None = None) -> dict:
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoria desconhecida: {categoria}")
    area = gpd.GeoSeries([shape(geom)], crs=4326).to_crs(METRIC_CRS).iloc[0]
    resumo = summarize(geom)
    pop = resumo["populacao_selecao"]["estimativa"]
    todos = load_pois()
    todos = todos[todos.categoria == categoria]
    dentro = todos[todos.within(area)]
    n = len(dentro)

    # distância do centro da área ao estabelecimento mais próximo (mesmo fora da área)
    d_centro = float(todos.distance(area.centroid).min()) if len(todos) else None

    # vizinho mais próximo médio entre os próprios concorrentes: baixo = aglomeração
    nn = None
    if n >= 2:
        xy = np.array([(p.x, p.y) for p in dentro.geometry])
        d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
        np.fill_diagonal(d, np.inf)
        nn = float(d.min(axis=1).mean())

    bairros = load_bairros().to_crs(METRIC_CRS).set_index("CD_BAIRRO").geometry
    por_bairro = []
    for r in resumo["bairros"]:
        qtd = int(todos.within(bairros[r["codigo"]]).sum())
        p = r["populacao_bairro"]
        por_bairro.append({"bairro": r["bairro"], "estabelecimentos": qtd, "populacao": p,
                           "hab_por_estab": round(p / qtd) if qtd and p else None})

    wgs = dentro.to_crs(4326)
    return {
        "do_ponto": _do_ponto(todos, *ponto) if ponto else None,
        "categoria": categoria, "rotulo": CATEGORIAS[categoria][0], "aviso": AVISO,
        "fonte": "OpenStreetMap (ODbL), © OpenStreetMap contributors",
        "coletado_em": str(todos.coletado_em.iloc[0]) if len(todos) else None,
        "estabelecimentos_na_area": n,
        "por_km2": round(n / (area.area / 1e6), 2),
        "populacao_estimada": pop,
        "hab_por_estabelecimento": round(pop / n) if n else None,
        "estab_por_10mil_hab": round(10000 * n / pop, 2) if pop else None,
        "dist_centro_ao_mais_proximo_m": None if d_centro is None else round(d_centro),
        "vizinho_mais_proximo_medio_m": None if nn is None else round(nn),
        "por_bairro": sorted(por_bairro, key=lambda b: -b["estabelecimentos"]),
        # NÃO é "lacuna de mercado": no OSM, bairros populosos sem registro costumam ser falha de mapeamento
        "bairros_sem_registro_osm": [b["bairro"] for b in por_bairro if b["estabelecimentos"] == 0 and (b["populacao"] or 0) > 5000],
        "pontos": [{"nome": nome if isinstance(nome, str) else None, "lon": g.x, "lat": g.y} for nome, g in zip(wgs.nome, wgs.geometry)],
    }
