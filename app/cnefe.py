"""CNEFE — Cadastro Nacional de Endereços para Fins Estatísticos (IBGE, Censo 2022). Uso: python -m app.cnefe

Minimização de dados (LGPD): rua, número, complemento, CEP e NOME do estabelecimento são lidos só para classificar e
NÃO são gravados. Só ficam coordenada, espécie, tipo e segmento (agregável). Nada aqui lista endereços individuais.

Limites do dado: é um retrato do Censo 2022 (não "hoje"); "outras finalidades" mistura comércio, serviços e indústria;
o segmento por palavra-chave no nome é INDICATIVO, sem validação contra verdade de campo.
"""
import json
import re
import unicodedata
import zipfile
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape

from .analysis import DATA, METRIC_CRS, load_bairros
from .ingest import RAW, _download
from .segmentos import SEGMENTOS

URL = ("https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/"
       "Arquivos_CNEFE/CSV/Municipio/13_AM/1302603_MANAUS.zip")
ARQ = DATA / "cnefe_manaus.npz"
META = DATA / "cnefe_manaus.json"

ESPECIES = {1: "Domicílio particular", 2: "Domicílio coletivo", 3: "Estabelecimento agropecuário", 4: "Estabelecimento de ensino",
            5: "Estabelecimento de saúde", 6: "Comércio, serviços e outras finalidades", 7: "Edificação em construção/reforma",
            8: "Estabelecimento religioso"}
TIPOS_MORADIA = {101: "Casa", 102: "Casa de vila/condomínio", 103: "Apartamento", 104: "Outros"}
# Grupos do mapa (≤3 cores, por legibilidade): residencial / comércio-serviços / institucional
GRUPO_MAPA = {1: "residencial", 2: "residencial", 6: "comercio_servicos", 4: "institucional", 5: "institucional", 8: "institucional"}

SEG_COD = {s: i + 2 for i, (s, _, _) in enumerate(SEGMENTOS)}  # 0 = não se aplica, 1 = sem identificação
SEG_COD |= {"sem_identificacao": 1, "outros": len(SEGMENTOS) + 2}
SEG_ROTULO = {SEG_COD[s]: r for s, r, _ in SEGMENTOS} | {1: "Sem identificação", len(SEGMENTOS) + 2: "Outros (não classificado)"}
SEM_ID = re.compile(r"^(SEM (NOME|DENOMINACAO|IDENTIFICACAO|PLACA)|S ?/ ?N|SN|NAO (TEM|IDENTIFICADO)|-+)$")


def _norm(s: pd.Series) -> pd.Series:
    return (s.fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.upper().str.strip())


def _segmentar(nome: pd.Series) -> np.ndarray:
    n = _norm(nome)
    seg = np.full(len(n), SEG_COD["outros"], dtype=np.int8)
    livre = np.ones(len(n), dtype=bool)
    sem = (n == "") | n.str.match(SEM_ID)
    seg[sem.to_numpy()], livre[sem.to_numpy()] = 1, False
    for s, _, palavras in SEGMENTOS:
        m = livre & n.str.contains(rf"\b(?:{palavras})\b", regex=True).to_numpy()
        seg[m], livre[m] = SEG_COD[s], False
    return seg


def ingest_cnefe() -> dict:
    z = zipfile.ZipFile(_download(URL, RAW / "cnefe_manaus.zip"))
    cols = ["LATITUDE", "LONGITUDE", "NV_GEO_COORD", "COD_ESPECIE", "DSC_ESTABELECIMENTO", "COD_INDICADOR_ESTAB_ENDERECO",
            "COD_INDICADOR_CONST_ENDERECO", "COD_INDICADOR_FINALIDADE_CONST", "COD_TIPO_ESPECI"]
    with z.open(z.namelist()[0]) as f:
        d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, usecols=cols)
    num = lambda c: pd.to_numeric(d[c], errors="coerce")
    esp = num("COD_ESPECIE").astype("Int8")
    seg = np.where(esp.eq(6).to_numpy(), _segmentar(d.DSC_ESTABELECIMENTO), 0).astype(np.int8)
    lon, lat = num("LONGITUDE").to_numpy(), num("LATITUDE").to_numpy()

    bairros = load_bairros()
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=4326)
    j = gpd.sjoin(pts, bairros[["CD_BAIRRO", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    cods = list(bairros.CD_BAIRRO)
    bairro = j.CD_BAIRRO.map({c: i for i, c in enumerate(cods)}).fillna(-1).astype(np.int16).to_numpy()

    fill = lambda c, dflt=0: num(c).fillna(dflt).astype(np.int16).to_numpy()
    np.savez_compressed(ARQ, lon=lon, lat=lat, nv=fill("NV_GEO_COORD").astype(np.int8), esp=esp.fillna(0).to_numpy().astype(np.int8),
                        tipo=fill("COD_TIPO_ESPECI"), seg=seg, estab=fill("COD_INDICADOR_ESTAB_ENDERECO").astype(np.int8),
                        fin=fill("COD_INDICADOR_FINALIDADE_CONST").astype(np.int8), bairro=bairro, bairros_cd=np.array(cods))
    e6 = seg[seg > 0]
    meta = {"fonte": "IBGE — CNEFE Censo Demográfico 2022 (Manaus)", "url": URL, "licenca": "Dados abertos IBGE (citar fonte)",
            "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "registros": int(len(d)),
            "por_especie": {ESPECIES[k]: int((esp == k).sum()) for k in ESPECIES},
            "pct_coordenada_de_endereco": round(float(100 * (num("NV_GEO_COORD") <= 3).mean()), 1),
            "segmentos_pct": {SEG_ROTULO[k]: round(float(100 * (e6 == k).mean()), 1) for k in SEG_ROTULO},
            # só conta segmento específico (não: sem nome, vago, genérico, outros)
            "pct_segmento_especifico": round(float(100 * np.isin(e6, [SEG_COD[s] for s, _, _ in SEGMENTOS if s not in ("vago", "generico")]).mean()), 1)}
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


_c: dict = {}


def _dados() -> dict:
    if "d" not in _c:
        z = np.load(ARQ, allow_pickle=False)
        d = {k: z[k] for k in z.files}
        x, y = Transformer.from_crs(4326, METRIC_CRS, always_xy=True).transform(d["lon"], d["lat"])
        d["x"], d["y"] = np.asarray(x), np.asarray(y)
        d["uso"] = d["nv"] <= 3  # só coordenada de ENDEREÇO (níveis 1–3); face/localidade/setor são centroides
        _c["d"] = d
    return _c["d"]


def _contagens(d: dict, m: np.ndarray) -> dict:
    esp, tipo, seg = d["esp"][m], d["tipo"][m], d["seg"][m]
    return {
        "total": int(m.sum()),
        "por_especie": {k: int((esp == k).sum()) for k in ESPECIES},
        "moradia": {TIPOS_MORADIA[k]: int(((esp == 1) & (tipo == k)).sum()) for k in TIPOS_MORADIA},
        "segmentos": {SEG_ROTULO[k]: int((seg == k).sum()) for k in sorted(SEG_ROTULO) if (seg == k).any()},
        "multiplos_estab": int(((esp == 6) & (d["estab"][m] >= 2)).sum()),
        "em_construcao_residencial": int(((esp == 7) & (d["fin"][m] == 1)).sum()),
    }


def _indices(c: dict) -> dict:
    e = c["por_especie"]
    dom, tot = e[1] + e[2], max(1, c["total"])
    nao_res = e[3] + e[4] + e[5] + e[6] + e[8]
    return {"pct_residencial": 100 * dom / tot, "pct_nao_residencial": 100 * nao_res / tot,
            "comercio_por_mil_dom": 1000 * e[6] / dom if dom else None,
            "pct_apartamentos": 100 * c["moradia"]["Apartamento"] / e[1] if e[1] else None,
            "pct_em_construcao": 100 * e[7] / tot}


def baseline() -> dict:
    if "b" not in _c:
        d = _dados()
        c = _contagens(d, d["uso"])
        _c["b"] = {"contagens": c, "indices": _indices(c)}
    return _c["b"]


def _interpretar(i: dict, b: dict) -> list[str]:
    """Regras explícitas e simples (limiares são heurísticos). Compara a área com a média de Manaus (mesmo dado)."""
    out = []
    pr = i["pct_residencial"]
    perfil = ("predominantemente residencial" if pr >= 85 else "de uso misto, com predominância residencial" if pr >= 60
              else "de uso misto/comercial (menos de 60% dos endereços são moradia)")
    out.append(f"Perfil de uso: área {perfil} — {pr:.0f}% dos endereços são domicílios (Manaus: {b['pct_residencial']:.0f}%).")
    if i["comercio_por_mil_dom"] is not None and b["comercio_por_mil_dom"]:
        r = i["comercio_por_mil_dom"] / b["comercio_por_mil_dom"]
        rot = "acima da média da cidade" if r > 1.25 else "abaixo da média da cidade" if r < 0.75 else "próxima da média da cidade"
        out.append(f"Intensidade de comércio e serviços: {i['comercio_por_mil_dom']:.0f} endereços por mil domicílios, {rot} "
                   f"({r:.1f}× a média de {b['comercio_por_mil_dom']:.0f}). Indica oferta existente relativa à demanda residencial, não potencial de mercado.")
    if i["pct_apartamentos"] is not None and b["pct_apartamentos"] is not None:
        a, ba = i["pct_apartamentos"], b["pct_apartamentos"]
        out.append(f"Verticalização: {a:.0f}% dos domicílios são apartamentos (Manaus: {ba:.0f}%) — "
                   + ("área mais verticalizada que a média." if a > ba * 1.5 else "área menos verticalizada que a média." if a < ba * 0.5 else "perfil de moradia próximo da média."))
    if b["pct_em_construcao"]:
        r = i["pct_em_construcao"] / b["pct_em_construcao"]
        out.append(f"Obras: {i['pct_em_construcao']:.1f}% dos endereços estavam em construção/reforma no Censo 2022 "
                   f"({r:.1f}× a média da cidade); sinal de dinâmica de ocupação na época, não de hoje.")
    return out


AVISOS = [
    "CNEFE é retrato do Censo 2022 (coleta 2022-2023): não reflete aberturas e fechamentos posteriores.",
    "\"Comércio, serviços e outras finalidades\" inclui indústria e serviços; o IBGE não separa comércio de serviço.",
    "Segmentos vêm de palavras-chave no nome do estabelecimento: classificação INDICATIVA, não validada; "
    "estabelecimentos sem nome ou não reconhecidos aparecem como tal.",
    "Endereços com múltiplos estabelecimentos (shoppings, galerias) contam 1 registro: a oferta real pode ser maior.",
    "Só coordenadas de endereço (níveis 1–3) entram nas contagens por área; face, localidade e setor ficam de fora.",
]


def analise(geom: dict, ponto: tuple[float, float] | None = None, aneis_m: list[int] | None = None) -> dict:
    d = _dados()
    poly = gpd.GeoSeries([shape(geom)], crs=4326).to_crs(METRIC_CRS).iloc[0]
    minx, miny, maxx, maxy = poly.bounds
    m = d["uso"] & (d["x"] >= minx) & (d["x"] <= maxx) & (d["y"] >= miny) & (d["y"] <= maxy)
    idx = np.flatnonzero(m)
    dentro = np.zeros(len(d["x"]), dtype=bool)
    dentro[idx] = shapely.contains_xy(poly, d["x"][idx], d["y"][idx])
    c = _contagens(d, dentro)
    i, b = _indices(c), baseline()
    por_bairro = []
    nomes = dict(zip(load_bairros().CD_BAIRRO, load_bairros().NM_BAIRRO))
    cods = d["bairros_cd"]
    for k in np.unique(d["bairro"][dentro]):
        if k < 0:
            continue
        mk = dentro & (d["bairro"] == k)
        ck = _contagens(d, mk)
        por_bairro.append({"bairro": nomes.get(str(cods[k])), "domicilios": ck["por_especie"][1], "comercio_servicos": ck["por_especie"][6]})
    out = {
        "contagens": c, "indices": i, "baseline_manaus": {"indices": b["indices"], "total": b["contagens"]["total"], "por_especie": b["contagens"]["por_especie"]},
        "interpretacao": _interpretar(i, b["indices"]) if c["total"] else ["Nenhum endereço CNEFE na área."],
        "por_bairro": sorted(por_bairro, key=lambda x: -x["comercio_servicos"])[:15],
        "qualidade": {"enderecos_na_area": c["total"], "pct_coordenada_de_endereco_manaus": json.loads(META.read_text(encoding="utf-8"))["pct_coordenada_de_endereco"]},
        "avisos": AVISOS, "fonte": "IBGE — CNEFE Censo 2022", "referencia": "2022",
    }
    if ponto:
        p = gpd.GeoSeries([Point(*ponto)], crs=4326).to_crs(METRIC_CRS).iloc[0]
        dist = np.hypot(d["x"] - p.x, d["y"] - p.y)
        out["por_anel"] = []
        for r in aneis_m or [250, 500, 1000, 2000]:
            mr = d["uso"] & (dist <= r)
            e = _contagens(d, mr)["por_especie"]
            out["por_anel"].append({"raio_m": r, "domicilios": e[1] + e[2], "comercio_servicos": e[6], "ensino": e[4], "saude": e[5], "religioso": e[8]})
    return out


def pontos(geom: dict, limite: int = 40_000) -> dict:
    """Coordenadas (sem texto de endereço) para o mapa, por grupo; trunca com aviso se a área for grande."""
    d = _dados()
    poly = gpd.GeoSeries([shape(geom)], crs=4326).to_crs(METRIC_CRS).iloc[0]
    minx, miny, maxx, maxy = poly.bounds
    idx = np.flatnonzero(d["uso"] & (d["x"] >= minx) & (d["x"] <= maxx) & (d["y"] >= miny) & (d["y"] <= maxy))
    idx = idx[shapely.contains_xy(poly, d["x"][idx], d["y"][idx])]
    total = len(idx)
    idx = idx[GRUPO_MAPA_MASK(d["esp"][idx])]
    truncado = len(idx) > limite
    idx = idx[:limite]
    feats = [{"type": "Feature", "properties": {"g": GRUPO_MAPA[int(d["esp"][i])]}, "geometry": {"type": "Point", "coordinates": [round(float(d["lon"][i]), 6), round(float(d["lat"][i]), 6)]}} for i in idx]
    return {"type": "FeatureCollection", "features": feats, "truncado": truncado, "total_na_area": total, "exibidos": len(idx)}


def GRUPO_MAPA_MASK(esp: np.ndarray) -> np.ndarray:
    return np.isin(esp, list(GRUPO_MAPA))


if __name__ == "__main__":
    print(json.dumps(ingest_cnefe(), ensure_ascii=False, indent=1))
