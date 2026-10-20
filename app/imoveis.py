"""Imóveis anunciados: importação de planilhas AUTORIZADAS (imobiliária parceira / base licenciada). Sem scraping.

Preço aqui é PREÇO ANUNCIADO, não de transação nem avaliação. Venda e aluguel nunca são misturados.
Dados DEMO (fictícios) ficam marcados `demo=1` e só entram nos indicadores se pedido explicitamente.
"""
import re
import sqlite3
import unicodedata
from datetime import date

import geopandas as gpd
import pandas as pd

from .analysis import DATA, load_bairros

DB = DATA / "plataforma.sqlite"
MIN_AMOSTRA = 5
FINALIDADES = {"venda", "aluguel"}
TIPOS = {"apartamento", "casa", "terreno", "comercial", "galpao", "outro"}
OBRIGATORIAS = ["finalidade", "tipo", "preco", "area_m2"]
# heurística de plausibilidade (R$/m²), para barrar erro de digitação, não para avaliar mercado
FAIXA_M2 = {"venda": (200, 100_000), "aluguel": (1, 1_000)}
BBOX_MANAUS = (-60.35, -3.35, -59.65, -2.75)  # minx, miny, maxx, maxy


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS imoveis (
        lote TEXT, fonte TEXT, licenca TEXT, data_coleta TEXT, demo INTEGER, id_anuncio TEXT, url TEXT,
        finalidade TEXT, tipo TEXT, preco REAL, area_m2 REAL, preco_m2 REAL, quartos INTEGER, vagas INTEGER,
        bairro_cd TEXT, bairro TEXT, lat REAL, lon REAL, chave TEXT)""")
    return con


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _num(v):
    """'R$ 1.234,56' / '1234.56' / 1234.5 → float; inválido → None."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def importar(df: pd.DataFrame, fonte: str, licenca: str, data_coleta: str, demo: bool = False) -> dict:
    """Valida linha a linha. Retorna aceitos e rejeitados com motivo; nada é corrigido em silêncio."""
    if not fonte.strip() or not licenca.strip():
        raise ValueError("fonte e licenca são obrigatórias (rastreabilidade)")
    date.fromisoformat(data_coleta)
    df = df.rename(columns={c: _norm(c).replace(" ", "_") for c in df.columns})
    falta = [c for c in OBRIGATORIAS if c not in df.columns]
    if falta:
        raise ValueError(f"colunas obrigatórias ausentes: {falta}")

    bairros = load_bairros()
    por_nome = {_norm(n): (cd, n) for cd, n in zip(bairros.CD_BAIRRO, bairros.NM_BAIRRO)}
    lote = f"{date.today():%Y%m%d}-{abs(hash((fonte, data_coleta, len(df)))) % 10**6:06d}"
    ok, rej, vistos = [], [], set()
    for i, r in df.iterrows():
        linha = i + 2  # cabeçalho = linha 1
        fin, tipo = _norm(r.finalidade), _norm(r.tipo)
        preco, area = _num(r.preco), _num(r.area_m2)
        if fin not in FINALIDADES:
            rej.append({"linha": linha, "motivo": f"finalidade inválida: {r.finalidade!r}"}); continue
        if tipo not in TIPOS:
            rej.append({"linha": linha, "motivo": f"tipo inválido: {r.tipo!r}"}); continue
        if not preco or preco <= 0 or not area or area <= 0:
            rej.append({"linha": linha, "motivo": "preço ou área ausente/não positivo"}); continue
        m2 = preco / area
        lo, hi = FAIXA_M2[fin]
        if not lo <= m2 <= hi:
            rej.append({"linha": linha, "motivo": f"R$/m² {m2:,.0f} fora da faixa plausível {lo}-{hi}"}); continue
        lat, lon = _num(r.get("lat")), _num(r.get("lon"))
        if (lat is None) != (lon is None):
            rej.append({"linha": linha, "motivo": "lat/lon incompletos"}); continue
        if lat is not None and not (BBOX_MANAUS[0] <= lon <= BBOX_MANAUS[2] and BBOX_MANAUS[1] <= lat <= BBOX_MANAUS[3]):
            rej.append({"linha": linha, "motivo": "coordenada fora de Manaus"}); continue
        idan = None if pd.isna(r.get("id_anuncio")) else str(r.get("id_anuncio"))
        chave = f"{idan}" if idan else f"{fin}|{tipo}|{preco}|{area}|{_norm(r.get('bairro', ''))}|{lat}|{lon}"
        if chave in vistos:
            rej.append({"linha": linha, "motivo": "anúncio duplicado no arquivo"}); continue
        vistos.add(chave)
        ok.append({"lote": lote, "fonte": fonte, "licenca": licenca,
                   "data_coleta": str(r.get("data_coleta") if pd.notna(r.get("data_coleta")) else data_coleta),
                   "demo": int(demo), "id_anuncio": idan, "url": None if pd.isna(r.get("url")) else r.get("url"),
                   "finalidade": fin, "tipo": tipo, "preco": preco, "area_m2": area, "preco_m2": m2,
                   "quartos": _num(r.get("quartos")), "vagas": _num(r.get("vagas")),
                   "bairro_nome": r.get("bairro"), "lat": lat, "lon": lon, "chave": chave})
    g = pd.DataFrame(ok)
    if len(g):
        g["bairro_cd"], g["bairro"] = None, None
        com_xy = g.lat.notna()
        if com_xy.any():  # coordenada manda; nome só quando não há coordenada
            pts = gpd.GeoDataFrame(g[com_xy], geometry=gpd.points_from_xy(g.lon[com_xy], g.lat[com_xy]), crs=4326)
            j = gpd.sjoin(pts, bairros[["CD_BAIRRO", "NM_BAIRRO", "geometry"]], how="left", predicate="within")
            j = j[~j.index.duplicated()]
            g.loc[j.index, "bairro_cd"], g.loc[j.index, "bairro"] = j.CD_BAIRRO, j.NM_BAIRRO
        for idx in g.index[g.bairro_cd.isna()]:
            hit = por_nome.get(_norm(g.at[idx, "bairro_nome"] or ""))
            if hit:
                g.at[idx, "bairro_cd"], g.at[idx, "bairro"] = hit
        with _con() as con:
            g.drop(columns=["bairro_nome"]).to_sql("imoveis", con, if_exists="append", index=False)
    return {"lote": lote, "aceitos": len(ok), "rejeitados": rej, "sem_bairro": int(g.bairro_cd.isna().sum()) if len(g) else 0}


def indicadores(finalidade: str, tipo: str | None = None, incluir_demo: bool = False) -> dict:
    if finalidade not in FINALIDADES:
        raise ValueError("finalidade deve ser venda ou aluguel")
    q, p = "SELECT * FROM imoveis WHERE finalidade=?", [finalidade]
    if tipo:
        q, p = q + " AND tipo=?", p + [tipo]
    if not incluir_demo:
        q += " AND demo=0"
    with _con() as con:
        df = pd.read_sql(q, con, params=p)
    linhas = []
    for (cd, nome), g in df.dropna(subset=["bairro_cd"]).groupby(["bairro_cd", "bairro"]):
        n = len(g)
        linha = {"bairro_cd": cd, "bairro": nome, "anuncios": n}
        if n >= MIN_AMOSTRA:
            linha |= {"mediana_m2": round(g.preco_m2.median(), 2), "p25_m2": round(g.preco_m2.quantile(.25), 2),
                      "p75_m2": round(g.preco_m2.quantile(.75), 2)}
        else:
            linha["nota"] = f"amostra insuficiente (<{MIN_AMOSTRA}); sem estatística"
        linhas.append(linha)
    unidade = "R$/m² (venda, preço anunciado)" if finalidade == "venda" else "R$/m²/mês (aluguel, valor anunciado)"
    return {"finalidade": finalidade, "tipo": tipo, "unidade": unidade, "demo_incluido": incluir_demo,
            "total_anuncios": len(df), "sem_bairro": int(df.bairro_cd.isna().sum()),
            "fontes": sorted(df.fonte.unique().tolist()), "datas_coleta": [df.data_coleta.min(), df.data_coleta.max()] if len(df) else None,
            "aviso": "Preço ANUNCIADO, não de transação nem avaliação formal. Anúncios de venda e aluguel não são combinados.",
            "bairros": sorted(linhas, key=lambda x: -x["anuncios"])}
