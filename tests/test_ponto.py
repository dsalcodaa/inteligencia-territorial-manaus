import math

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, shape

from app import ponto
from app.analysis import METRIC_CRS, load_bairros, summarize
from app.concorrencia import concorrencia
from app.main import app

c = TestClient(app)
CENTRO = (-60.0217, -3.1304)  # lon, lat — centro de Manaus


def _km2(geom):
    return gpd.GeoSeries([shape(geom)], crs=4326).to_crs(METRIC_CRS).iloc[0].area / 1e6


def test_circulo_area_bate_com_pi_r2():
    g = ponto.circulo(*CENTRO, 1000)
    assert abs(_km2(g) - math.pi) / math.pi < 0.01  # polígono de 64 lados ≈ círculo


@pytest.mark.parametrize("raio", [50, 25_000])
def test_raio_fora_do_limite(raio):
    with pytest.raises(ValueError):
        ponto.circulo(*CENTRO, raio)


def test_ponto_fora_de_manaus_rejeitado():
    assert c.post("/api/empreendimento", json={"lon": -46.6, "lat": -23.5, "raio_m": 1000}).status_code == 422


def test_bairro_do_ponto_e_dados_oficiais():
    b = load_bairros()
    ref = b[b.NM_BAIRRO == "Centro"].iloc[0]
    p = ref.geometry.representative_point()
    r = c.post("/api/empreendimento", json={"lon": p.x, "lat": p.y, "raio_m": 800}).json()
    assert r["bairro"]["nome"] == "Centro" and r["bairro"]["populacao"] == ref.pessoas
    assert "linha reta" in r["aviso"]


def test_ponto_no_rio_sem_bairro_nao_inventa():
    b = load_bairros()
    minx, miny, maxx, maxy = b.total_bounds
    uniao = b.union_all()
    vazio = next((x, y) for x in (minx + i * (maxx - minx) / 20 for i in range(21))
                 for y in (miny + j * (maxy - miny) / 20 for j in range(21)) if not uniao.contains(Point(x, y)))
    r = c.post("/api/empreendimento", json={"lon": vazio[0], "lat": vazio[1], "raio_m": 500})
    assert r.status_code == 200 and r.json()["bairro"] is None


def test_populacao_cresce_com_o_raio():
    pops = [summarize(ponto.circulo(*CENTRO, r))["populacao_selecao"]["estimativa"] for r in (500, 1000, 2000)]
    assert pops[0] < pops[1] < pops[2]


def test_aneis_acumulados_e_dentro_do_raio():
    g = ponto.circulo(*CENTRO, 2000)
    r = concorrencia(g, "farmacia", CENTRO)["do_ponto"]
    n = [a["estabelecimentos"] for a in r["aneis"]]
    assert n == sorted(n) and n[-1] > 0
    assert len(r["mais_proximos"]) == 5
    assert [m["distancia_m"] for m in r["mais_proximos"]] == sorted(m["distancia_m"] for m in r["mais_proximos"])
    assert concorrencia(g, "farmacia")["do_ponto"] is None  # sem ponto, sem bloco


def test_uniao_bairros_e_codigo_invalido():
    b = load_bairros()
    sel = b[b.NM_BAIRRO.isin(["Centro", "Flores"])]
    r = c.post("/api/bairros/uniao", json={"codigos": list(sel.CD_BAIRRO)}).json()
    soma = gpd.GeoSeries(sel.geometry, crs=4326).to_crs(METRIC_CRS).area.sum() / 1e6
    assert abs(_km2(r["geometry"]) - soma) / soma < 0.02 and r["bairros"] == ["Centro", "Flores"]
    assert c.post("/api/bairros/uniao", json={"codigos": ["x"]}).status_code == 422
    assert c.post("/api/bairros/uniao", json={"codigos": []}).status_code == 422


def test_pdf_nao_troca_virgula_da_prosa_por_ponto():
    import pymupdf
    from app.report import build_pdf
    emp = {"lon": CENTRO[0], "lat": CENTRO[1], "raio_m": 1000, "nome": "Loja", "bairro": ponto.bairro_do_ponto(*CENTRO)}
    pdf = build_pdf(ponto.circulo(*CENTRO, 1000), empreendimento=emp)
    txt = " ".join(" ".join(p.get_text().split()) for p in pymupdf.open(stream=pdf))
    assert "Censo 2022, escala setor censitário" in txt
    assert "renda mediana do responsável R$" in txt and ", renda mediana" in txt


def test_analise_de_bairros_multipoligono_e_pdf_de_empreendimento():
    b = load_bairros()
    cods = list(b[b.NM_BAIRRO.isin(["Centro", "Ponta Negra"])].CD_BAIRRO)  # não adjacentes → MultiPolygon
    geom = c.post("/api/bairros/uniao", json={"codigos": cods}).json()["geometry"]
    assert summarize(geom)["populacao_selecao"]["estimativa"] > 0
    r = c.post("/api/report/pdf", json={"geometry": geom})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    emp = c.post("/api/empreendimento", json={"lon": CENTRO[0], "lat": CENTRO[1], "raio_m": 1000}).json()
    r = c.post(f"/api/report/pdf?categoria=farmacia&lon={CENTRO[0]}&lat={CENTRO[1]}&raio_m=1000&nome=Loja%20Teste", json={"geometry": emp["geometry"]})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
