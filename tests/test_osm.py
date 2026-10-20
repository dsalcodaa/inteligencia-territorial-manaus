import json

import pytest
from fastapi.testclient import TestClient

from app.acessibilidade import acessibilidade
from app.main import app
from app.pois import CATEGORIAS, _categoria
from tests.test_analysis import FAR, SQUARE


def test_categoria_ordem_e_residuo():
    assert _categoria({"shop": "supermarket"}) == "supermercado"
    assert _categoria({"shop": "bakery"}) == "padaria"
    assert _categoria({"shop": "coisa_rara"}) == "outro_comercio"  # resíduo só para shop sem categoria própria
    assert _categoria({"amenity": "pharmacy", "shop": "chemist"}) == "farmacia"
    assert _categoria({"highway": "bus_stop"}) is None
    assert len(CATEGORIAS) > 20


def test_acessibilidade_area_urbana():
    a = acessibilidade(SQUARE)
    assert a["vias_km"] and a["densidade_vias_km_por_km2"] > 0
    assert a["via_arterial_mais_proxima"]["distancia_m"] >= 0
    assert a["infra_na_area"].get("ponto_onibus", 0) > 0
    assert "linha reta" in a["aviso"] and "NÃO são anúncios" in a["nota_edificacoes"]


def test_ruas_locais_somam_na_densidade():
    a = acessibilidade(SQUARE)
    assert a["vias_locais_km"] > 0
    km_classes = sum(a["vias_km"].values())
    assert a["densidade_vias_km_por_km2"] > km_classes / a["area_km2"]


def test_acessibilidade_area_vazia_nao_inventa():
    a = acessibilidade(FAR)
    assert a["vias_km"] == {} and a["infra_na_area"] == {} and a["edificacoes_nao_residenciais"] == []


def test_http_json_estrito_e_camadas():
    c = TestClient(app)
    r = c.post("/api/acessibilidade", json={"geometry": SQUARE})
    assert r.status_code == 200
    json.loads(r.text, parse_constant=lambda x: pytest.fail(f"{x} no JSON"))
    for nome in ("vias", "infra", "edificacoes"):
        g = c.get(f"/api/camadas/{nome}")
        assert g.status_code == 200 and g.json()["features"]
        json.loads(g.text, parse_constant=lambda x: pytest.fail(f"{x} em {nome}"))
    assert c.get("/api/camadas/xx").status_code == 404
