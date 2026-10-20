import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import imoveis
from app.main import app


@pytest.fixture(autouse=True)
def db_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(imoveis, "DB", tmp_path / "t.sqlite")


def _df(n=6, fin="venda", preco=600_000, bairro="Flores"):
    return pd.DataFrame([{"id_anuncio": f"{fin}{i}", "finalidade": fin, "tipo": "apartamento", "preco": preco + i,
                          "area_m2": 100, "bairro": bairro} for i in range(n)])


def test_import_validation_reasons():
    bad = pd.DataFrame([
        {"finalidade": "troca", "tipo": "casa", "preco": 1e5, "area_m2": 50},
        {"finalidade": "venda", "tipo": "casa", "preco": None, "area_m2": 50},
        {"finalidade": "venda", "tipo": "casa", "preco": 1000, "area_m2": 100},          # R$10/m² implausível
        {"finalidade": "venda", "tipo": "casa", "preco": 4e5, "area_m2": 100, "lat": 0, "lon": 0},
        {"finalidade": "venda", "tipo": "casa", "preco": "R$ 400.000,00", "area_m2": "100"},  # formato BR aceito
    ])
    r = imoveis.importar(bad, "teste", "licença de teste", "2026-01-01")
    assert r["aceitos"] == 1 and len(r["rejeitados"]) == 4


def test_rejects_without_source_or_missing_columns():
    with pytest.raises(ValueError):
        imoveis.importar(_df(), "", "x", "2026-01-01")
    with pytest.raises(ValueError):
        imoveis.importar(_df().drop(columns="preco"), "f", "l", "2026-01-01")


def test_duplicates_dropped_and_sample_floor():
    d = pd.concat([_df(3), _df(3)])
    r = imoveis.importar(d, "f", "l", "2026-01-01")
    assert r["aceitos"] == 3 and len(r["rejeitados"]) == 3
    ind = imoveis.indicadores("venda")
    assert "mediana_m2" not in ind["bairros"][0] and "amostra insuficiente" in ind["bairros"][0]["nota"]


def test_median_and_venda_aluguel_not_mixed():
    imoveis.importar(_df(6, "venda", 600_000), "f", "l", "2026-01-01")
    imoveis.importar(_df(6, "aluguel", 3_000), "f", "l", "2026-01-01")
    v, a = imoveis.indicadores("venda"), imoveis.indicadores("aluguel")
    assert v["bairros"][0]["anuncios"] == 6 and a["bairros"][0]["anuncios"] == 6
    assert 5990 < v["bairros"][0]["mediana_m2"] < 6010 and 29 < a["bairros"][0]["mediana_m2"] < 31
    assert "mês" in a["unidade"] and "anunciado" in v["aviso"].lower()


def test_demo_excluded_by_default():
    imoveis.importar(_df(6), "DEMO", "l", "2026-01-01", demo=True)
    assert imoveis.indicadores("venda")["total_anuncios"] == 0
    assert imoveis.indicadores("venda", incluir_demo=True)["total_anuncios"] == 6


def test_upload_endpoint_locked_without_token(monkeypatch):
    c = TestClient(app)
    files, data = {"arquivo": ("a.csv", b"finalidade,tipo,preco,area_m2\n")}, {"fonte": "f", "licenca": "l", "data_coleta": "2026-01-01"}
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert c.post("/api/imoveis/importar", files=files, data=data).status_code == 403
    monkeypatch.setenv("ADMIN_TOKEN", "segredo")
    assert c.post("/api/imoveis/importar", files=files, data=data, headers={"x-admin-token": "errado"}).status_code == 401
    csv = _df(6).to_csv(index=False).encode()
    ok = c.post("/api/imoveis/importar", files={"arquivo": ("a.csv", csv)}, data=data, headers={"x-admin-token": "segredo"})
    assert ok.status_code == 200 and ok.json()["aceitos"] == 6
