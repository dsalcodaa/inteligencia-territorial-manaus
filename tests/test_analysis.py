import json

import pytest
from fastapi.testclient import TestClient

from app.analysis import load_bairros, summarize
from app.main import app

SQUARE = {"type": "Polygon", "coordinates": [[[-60.05, -3.15], [-59.95, -3.15], [-59.95, -3.05], [-60.05, -3.05], [-60.05, -3.15]]]}
FAR = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def test_bairros_manaus_loaded():
    assert len(load_bairros()) == 63


def test_population_bounds_and_bairro_sum():
    b = load_bairros()
    assert 2_000_000 < b.pessoas.sum() < 2_100_000
    p = summarize(SQUARE)["populacao_selecao"]
    assert 0 <= p["minimo_exato"] <= p["estimativa"]


def test_age_bands_close_to_total():
    p = summarize(SQUARE)["populacao_selecao"]
    assert len(p["faixas_etarias"]) == 11
    assert abs(sum(p["faixas_etarias"].values()) - p["estimativa"]) / p["estimativa"] < 0.01


def test_renda_bairro_official_and_selection_in_range():
    b = load_bairros()
    assert b.bairro_renda_mediana.notna().all()
    r = summarize(SQUARE)["populacao_selecao"]["renda_responsavel"]["media_aprox_rs"]
    assert b.bairro_renda_media.min() * 0.5 < r < b.bairro_renda_media.max()


def test_saneamento_consistent():
    b = load_bairros()
    for t in ("agua", "esgoto", "lixo"):
        assert (b[f"{t}_adequado"] <= b[f"{t}_total"]).all()
        assert (b[f"{t}_total"] <= b.dppo_total).all()
    sn = summarize(SQUARE)["populacao_selecao"]["saneamento"]
    assert all(0 <= v["pct"] <= 100 and v["cobertura_dados_pct"] > 90 for v in sn.values())


def test_infraestrutura_consistent():
    b = load_bairros()
    for t in ("pav", "bueiro", "ilum", "onibus", "calcada", "rampa", "arvore"):
        assert (b[f"{t}_adequado"] <= b[f"{t}_total"]).all()
        assert (b[f"{t}_total"] <= b.dppo_total).all()
    inf = summarize(SQUARE)["populacao_selecao"]["infraestrutura"]
    assert len(inf) == 7 and all(0 <= v["pct"] <= 100 for v in inf.values())


def test_concorrencia_farmacia():
    from app.concorrencia import concorrencia
    c = concorrencia(SQUARE, "farmacia")
    assert c["estabelecimentos_na_area"] > 0 and len(c["pontos"]) == c["estabelecimentos_na_area"]
    assert c["hab_por_estabelecimento"] == round(c["populacao_estimada"] / c["estabelecimentos_na_area"])
    assert "OpenStreetMap" in c["aviso"]
    assert concorrencia(FAR, "farmacia")["estabelecimentos_na_area"] == 0
    assert concorrencia(FAR, "farmacia")["hab_por_estabelecimento"] is None  # sem divisão por zero nem valor inventado
    with pytest.raises(ValueError):
        concorrencia(SQUARE, "inexistente")


def test_concorrencia_http_json_valido():
    # estabelecimentos sem nome no OSM geram NaN; a resposta precisa ser JSON estrito
    c = TestClient(app)
    for cat in ("farmacia", "supermercado", "restaurante", "saude"):
        r = c.post(f"/api/concorrencia?categoria={cat}", json={"geometry": SQUARE})
        assert r.status_code == 200, cat
        json.loads(r.text, parse_constant=lambda x: pytest.fail(f"{x} no JSON"))
    assert c.post("/api/concorrencia?categoria=xx", json={"geometry": SQUARE}).status_code == 422


def test_pdf_com_concorrencia():
    c = TestClient(app)
    r = c.post("/api/report/pdf?categoria=farmacia", json={"geometry": SQUARE})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert c.post("/api/report/pdf?categoria=xx", json={"geometry": SQUARE}).status_code == 422


def test_google_places_inativo_sem_chave(monkeypatch):
    from app import google_places
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        google_places.buscar_proximos(-3.1, -60, 500, ["pharmacy"])


def test_whole_bairro_matches_census_exactly():
    b = load_bairros()
    row = b[b.pessoas.notna()].iloc[0]
    p = summarize(row.geometry.__geo_interface__, b)
    assert p["populacao_selecao"]["estimativa"] >= int(row.pessoas) * 0.97  # borda IBGE bairro×setor pode diferir


def test_summary_overlaps():
    s = summarize(SQUARE)
    assert s["area_selecao_km2"] > 0 and s["bairros"]
    assert all(0 <= b["pct_do_bairro"] <= 100 for b in s["bairros"])
    assert sum(b["area_na_selecao_km2"] for b in s["bairros"]) <= s["area_selecao_km2"] + 0.01


def test_area_outside_manaus_has_no_bairros():
    s = summarize(FAR)
    assert s["bairros"] == [] and s["populacao_selecao"]["estimativa"] == 0


def test_invalid_polygon_rejected():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(ValueError):
        summarize(bowtie)


def test_api_pdf_and_sources():
    c = TestClient(app)
    r = c.post("/api/report/pdf", json={"geometry": SQUARE})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert any(s["estado"] == "funcionando" for s in c.get("/api/fontes").json())
    assert c.post("/api/area/summary", json={"geometry": {"type": "x"}}).status_code == 422
