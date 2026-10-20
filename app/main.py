import hmac
import io
import json
import os

import pandas as pd
from fastapi import FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cnefe, google_places, imoveis, ponto
import geopandas as gpd

from .acessibilidade import acessibilidade
from .analysis import DATA, load_indicators, summarize
from .concorrencia import concorrencia
from .pois import CATEGORIAS
from .report import build_pdf
from .sources import SOURCES

app = FastAPI(title="Plataforma de Inteligência Territorial")


class Area(BaseModel):
    geometry: dict  # GeoJSON Polygon, WGS84


@app.get("/api/bairros")
def bairros():
    return json.loads((DATA / "bairros_manaus.geojson").read_text(encoding="utf-8"))


@app.get("/api/indicadores")
def indicadores():
    return load_indicators()


@app.get("/api/fontes")
def fontes():
    return SOURCES


@app.post("/api/area/summary")
def area_summary(a: Area):
    try:
        return summarize(a.geometry)
    except Exception as e:
        raise HTTPException(422, f"geometria inválida: {e}")


@app.get("/api/categorias")
def categorias():
    return {k: v[0] for k, v in CATEGORIAS.items()}


class Ponto(BaseModel):
    lon: float
    lat: float
    raio_m: float = 1000


class Codigos(BaseModel):
    codigos: list[str]


@app.post("/api/empreendimento")
def api_empreendimento(p: Ponto):
    try:
        return ponto.empreendimento(p.lon, p.lat, p.raio_m)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/enderecos")
def api_enderecos(a: Area, lon: float | None = None, lat: float | None = None, raio_m: float | None = None):
    emp = (lon, lat) if lon is not None and lat is not None else None
    try:
        return cnefe.analise(a.geometry, emp, ponto.raios_aneis(raio_m) if emp and raio_m else None)
    except FileNotFoundError:
        raise HTTPException(503, "CNEFE não carregado: rode python -m app.cnefe")
    except Exception as e:
        raise HTTPException(422, f"geometria inválida: {e}")


@app.post("/api/enderecos/pontos")
def api_enderecos_pontos(a: Area):
    try:
        return cnefe.pontos(a.geometry)
    except FileNotFoundError:
        raise HTTPException(503, "CNEFE não carregado: rode python -m app.cnefe")
    except Exception as e:
        raise HTTPException(422, f"geometria inválida: {e}")


@app.post("/api/bairros/uniao")
def api_bairros_uniao(c: Codigos):
    try:
        return ponto.uniao_bairros(c.codigos)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/concorrencia")
def api_concorrencia(a: Area, categoria: str, lon: float | None = None, lat: float | None = None):
    try:
        return concorrencia(a.geometry, categoria, (lon, lat) if lon is not None and lat is not None else None)
    except ValueError as e:
        raise HTTPException(422, str(e))


MAX_UPLOAD = 10 * 1024 * 1024


@app.post("/api/imoveis/importar")
async def imoveis_importar(arquivo: UploadFile, fonte: str = Form(), licenca: str = Form(), data_coleta: str = Form(),
                           x_admin_token: str | None = Header(default=None)):
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        raise HTTPException(403, "importação desativada: defina ADMIN_TOKEN no servidor")
    if not hmac.compare_digest(x_admin_token or "", token):
        raise HTTPException(401, "token inválido")
    raw = await arquivo.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "arquivo maior que 10 MB")
    try:
        nome = (arquivo.filename or "").lower()
        if nome.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(raw))
        elif nome.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding="latin1")
        else:
            raise ValueError("use .csv ou .xlsx")
        return imoveis.importar(df, fonte, licenca, data_coleta)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/imoveis/indicadores")
def imoveis_indicadores(finalidade: str, tipo: str | None = None, incluir_demo: bool = False):
    try:
        return imoveis.indicadores(finalidade, tipo, incluir_demo)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/acessibilidade")
def api_acessibilidade(a: Area):
    try:
        return acessibilidade(a.geometry)
    except Exception as e:
        raise HTTPException(422, f"geometria inválida: {e}")


CAMADAS = {"vias": "vias_osm", "infra": "infra_osm", "edificacoes": "edificacoes_osm"}


@app.get("/api/camadas/{nome}")
def camada(nome: str):
    if nome not in CAMADAS:
        raise HTTPException(404, "camada desconhecida")
    return json.loads(gpd.read_file(DATA / f"{CAMADAS[nome]}.gpkg").to_json())


@app.get("/api/google/status")
def google_status():
    return {"configurado": google_places.configurado(), "estado": "funcionando" if google_places.configurado() else "aguardando_credenciais"}


@app.post("/api/report/pdf")
def report_pdf(a: Area, categoria: str | None = None, lon: float | None = None, lat: float | None = None,
               raio_m: float | None = None, nome: str | None = None):
    try:
        emp = None
        if lon is not None and lat is not None:
            emp = {"lon": lon, "lat": lat, "raio_m": raio_m, "nome": (nome or "Empreendimento")[:80],
                   "bairro": ponto.bairro_do_ponto(lon, lat)}
        pdf = build_pdf(a.geometry, categoria=categoria, empreendimento=emp)
    except Exception as e:
        raise HTTPException(422, f"geometria inválida: {e}")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=diagnostico.pdf"})


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
