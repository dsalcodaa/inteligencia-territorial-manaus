import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pymupdf
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from app import cnefe, ponto
from app.analysis import METRIC_CRS
from app.main import app
from app.report import build_pdf
from tests.test_analysis import FAR, SQUARE

c = TestClient(app)
CENTRO = (-60.0217, -3.1304)


def seg(nomes):
    s = cnefe._segmentar(pd.Series(nomes))
    return [cnefe.SEG_ROTULO[int(x)] for x in s]


def test_segmentos_por_palavra_chave_com_acento_e_regionalismo():
    r = seg(["FARMACIA SAO JOSE", "BAR DO CARECA", "AÇAÍ DA TIA", "TABERNA DO ZE", "PANIFICADORA BOM PAO", "MAT DE CONSTRUCAO BEIJA FLOR",
             "BRECHÓ CHIQUE", "FRUTARIA DONA MARIA"])
    assert r == ["Saúde e bem-estar", "Alimentação e bebidas", "Alimentação e bebidas", "Alimentação e bebidas",
                 "Alimentação e bebidas", "Construção e ofícios", "Varejo e variedades", "Mercados, feiras e açougues"]


def test_vago_tem_prioridade_e_casos_sem_identificacao():
    assert seg(["PONTO VAGO", "BAR VAGO", "SEM NOME", "SEM DENOMINACAO", "", None, "PONTO COMERCIAL", "XYZW QQQ"]) == [
        "Ponto vago, fechado ou à venda/aluguel", "Ponto vago, fechado ou à venda/aluguel", "Sem identificação", "Sem identificação",
        "Sem identificação", "Sem identificação", "Ponto comercial sem especificação", "Outros (não classificado)"]
    assert seg(["BARBEARIA DO JOAO"]) == ["Beleza"]  # \b: "BAR" não pode casar dentro de BARBEARIA


def test_dados_batem_com_o_censo_e_cobertura_de_coordenada():
    d = cnefe._dados()
    esp1 = int((d["esp"] == 1).sum())
    censo = gpd.read_file("data/setores_manaus.gpkg", ignore_geometry=True).domicilios.sum()
    assert abs(esp1 - censo) / censo < 0.01  # CNEFE × Censo: −0,5% medido
    assert d["uso"].mean() > 0.99


def test_nenhum_texto_pessoal_foi_gravado():
    z = np.load(cnefe.ARQ, allow_pickle=False)
    assert not {"nome", "logradouro", "numero", "cep", "estabelecimento"} & set(z.files)
    for k in z.files:  # só numéricos; a única exceção são os códigos de bairro do IBGE
        assert z[k].dtype.kind in "iuf" or k == "bairros_cd", k
    meta = json.loads(cnefe.META.read_text(encoding="utf-8"))
    assert "DSC_ESTABELECIMENTO" not in json.dumps(meta)


def test_analise_contagens_e_interpretacao():
    a = cnefe.analise(ponto.circulo(*CENTRO, 1000))
    ce = a["contagens"]
    assert ce["total"] == sum(ce["por_especie"].values())
    assert ce["por_especie"][6] == sum(v for k, v in ce["segmentos"].items())  # segmentos só existem p/ espécie 6
    assert a["indices"]["pct_residencial"] < a["baseline_manaus"]["indices"]["pct_residencial"]  # Centro é mais misto que a cidade
    assert any("Perfil de uso" in t for t in a["interpretacao"]) and a["avisos"]


def test_area_vazia_nao_quebra_nem_inventa():
    a = cnefe.analise(FAR)
    assert a["contagens"]["total"] == 0 and a["interpretacao"] == ["Nenhum endereço CNEFE na área."]
    assert a["indices"]["comercio_por_mil_dom"] is None


def test_aneis_acumulados_e_geometrias_aninhadas():
    assert ponto.raios_aneis(1000) == [250, 500, 1000] and ponto.raios_aneis(800) == [250, 500, 800]
    a = cnefe.analise(ponto.circulo(*CENTRO, 2000), CENTRO, ponto.raios_aneis(2000))["por_anel"]
    dom = [x["domicilios"] for x in a]
    assert dom == sorted(dom) and a[-1]["raio_m"] == 2000
    e = c.post("/api/empreendimento", json={"lon": CENTRO[0], "lat": CENTRO[1], "raio_m": 2000}).json()
    areas = [gpd.GeoSeries([shape(x["geometry"])], crs=4326).to_crs(METRIC_CRS).iloc[0].area for x in e["aneis"]]
    assert [x["raio_m"] for x in e["aneis"]] == [250, 500, 1000, 2000] and areas == sorted(areas)


def test_http_json_estrito_pontos_sem_endereco_e_truncamento():
    r = c.post(f"/api/enderecos?lon={CENTRO[0]}&lat={CENTRO[1]}&raio_m=1000", json={"geometry": ponto.circulo(*CENTRO, 1000)})
    assert r.status_code == 200 and r.json()["por_anel"]
    json.loads(r.text, parse_constant=lambda x: pytest.fail(f"{x} no JSON"))
    p = c.post("/api/enderecos/pontos", json={"geometry": ponto.circulo(*CENTRO, 500)}).json()
    assert p["features"] and all(set(f["properties"]) == {"g"} for f in p["features"])  # só grupo; sem texto de endereço
    grande = c.post("/api/enderecos/pontos", json={"geometry": SQUARE}).json()
    assert grande["truncado"] and grande["exibidos"] == 40_000 and grande["total_na_area"] > 40_000
    assert c.post("/api/enderecos", json={"geometry": {"type": "x"}}).status_code == 422


def test_pdf_tem_secao_de_enderecos_com_comparacao():
    emp = {"lon": CENTRO[0], "lat": CENTRO[1], "raio_m": 1000, "nome": "Loja", "bairro": ponto.bairro_do_ponto(*CENTRO)}
    pdf = build_pdf(ponto.circulo(*CENTRO, 1000), empreendimento=emp)
    txt = " ".join(" ".join(p.get_text().split()) for p in pymupdf.open(stream=pdf))
    assert "Endereços por tipo (CNEFE, Censo 2022)" in txt and "% de Manaus" in txt and "Limitações do CNEFE" in txt
    assert "Raio (m)" in txt  # tabela por anel só quando há empreendimento
