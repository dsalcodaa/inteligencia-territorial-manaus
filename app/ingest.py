"""Baixa e normaliza dados das fontes abertas. Uso: python -m app.ingest"""
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import httpx

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "raw"
GPKG_URL = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
    "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/bairros/gpkg/UF/AM/AM_bairros_CD2022.gpkg"
)
MANAUS = "1302603"
SIDRA = f"https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos/2022/variaveis/93?localidades=N6[{MANAUS}]"
BCB = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados/ultimos/{}?formato=json"
BCB_SERIES = {432: "Meta Selic (% a.a.)", 433: "IPCA (% a.m.)"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest_bairros() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    gpkg = RAW / "AM_bairros_CD2022.gpkg"
    if not gpkg.exists():
        gpkg.write_bytes(httpx.get(GPKG_URL, timeout=300, follow_redirects=True).raise_for_status().content)
    g = gpd.read_file(gpkg)
    g = g[g.CD_MUN == MANAUS][["CD_BAIRRO", "NM_BAIRRO", "NM_SUBDIST", "geometry"]].to_crs(4326)
    g.to_file(DATA / "bairros_manaus.geojson", driver="GeoJSON")
    return len(g)


AGREG_URL = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/"
             "Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip")
SETORES_URL = GPKG_URL.replace("bairros/gpkg/UF/AM/AM_bairros_CD2022", "setores/gpkg/UF/AM/AM_setores_CD2022")


DEMOG_URL = AGREG_URL.replace("basico_BR_20260520", "demografia_BR")
FAIXAS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-39", "40-49", "50-59", "60-69", "70+"]
# Dicionário IBGE: V01031..V01041 = faixas etárias; V01007/V01008 = sexo masculino/feminino
DEMOG_COLS = {"V01007": "homens", "V01008": "mulheres",
              **{f"V{1031 + i:05d}": f"idade_{f}" for i, f in enumerate(FAIXAS)}}


def _download(url: str, dest: Path) -> Path:
    if not dest.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=900, follow_redirects=True) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return dest


def ingest_setores() -> dict:
    """Setores de Manaus + totais do Censo 2022 (v0001 pessoas, v0002 domicílios, v0007 dom. part. ocupados).

    Valores '.' (sigilo/ausente) viram NaN, nunca zero. População por bairro = soma dos setores (observado).
    """
    import io
    import zipfile

    import pandas as pd

    g = gpd.read_file(_download(SETORES_URL, RAW / "AM_setores_CD2022.gpkg"))
    g = g[g.CD_MUN == MANAUS][["CD_SETOR", "CD_BAIRRO", "NM_BAIRRO", "geometry"]]
    z = zipfile.ZipFile(_download(AGREG_URL, RAW / "basico.zip"))
    with z.open(z.namelist()[0]) as f:
        df = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, usecols=["CD_SETOR", "v0001", "v0002", "v0007"])
    df = df[df.CD_SETOR.isin(g.CD_SETOR)].replace(".", None)
    for c, n in (("v0001", "pessoas"), ("v0002", "domicilios"), ("v0007", "dom_ocupados")):
        df[n] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce")
    g = g.merge(df[["CD_SETOR", "pessoas", "domicilios", "dom_ocupados"]], on="CD_SETOR", how="left").to_crs(4326)

    zd = zipfile.ZipFile(_download(DEMOG_URL, RAW / "demografia.zip"))
    with zd.open(zd.namelist()[0]) as f:
        dm = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, usecols=["CD_setor", *DEMOG_COLS])
    dm = dm.rename(columns={"CD_setor": "CD_SETOR"})  # capitalização difere do arquivo básico
    dm = dm[dm.CD_SETOR.isin(g.CD_SETOR)].replace(".", None)
    for c in DEMOG_COLS:  # '.' → NaN (nunca zero)
        dm[c] = pd.to_numeric(dm[c], errors="coerce")
    g = g.merge(dm.rename(columns=DEMOG_COLS), on="CD_SETOR", how="left")
    g.to_file(DATA / "setores_manaus.gpkg", driver="GPKG")

    bairros = gpd.read_file(DATA / "bairros_manaus.geojson")
    agg = g.groupby("CD_BAIRRO")[["pessoas", "domicilios", "dom_ocupados"]].sum(min_count=1).reset_index()
    bairros.drop(columns=["pessoas", "domicilios", "dom_ocupados"], errors="ignore").merge(agg, on="CD_BAIRRO", how="left") \
        .to_file(DATA / "bairros_manaus.geojson", driver="GeoJSON")
    return {"setores": len(g), "sem_bairro": int(g.CD_BAIRRO.isna().sum()), "pessoas": int(g.pessoas.sum()),
            "setores_sem_valor": int(g.pessoas.isna().sum())}


RENDA_BASE = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
              "Agregados_por_{}_renda_responsavel_BR_20260508_csv.zip")


def _renda_csv(kind: str):
    """Lê CSV de renda do IBGE. V06001 responsáveis, V06004 média, V06006 mediana (rendimento nominal mensal, R$).

    Separador decimal varia entre arquivos (setores '.', bairros ','); '.' isolado = sigilo → NaN.
    """
    import zipfile

    import pandas as pd

    z = zipfile.ZipFile(_download(RENDA_BASE.format(kind), RAW / f"renda_{kind}.zip"))
    with z.open(z.namelist()[0]) as f:
        df = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
    for src, dst in (("V06001", "responsaveis"), ("V06004", "renda_media"), ("V06006", "renda_mediana")):
        df[dst] = pd.to_numeric(df[src].str.replace(",", "."), errors="coerce")
    return df


def ingest_renda() -> dict:
    """Renda do responsável (Censo 2022): bairros = valor oficial IBGE; setores = base da estimativa por área."""
    s = gpd.read_file(DATA / "setores_manaus.gpkg").drop(columns=["responsaveis", "renda_media", "renda_mediana"], errors="ignore")
    rs = _renda_csv("setores")[["CD_SETOR", "responsaveis", "renda_media", "renda_mediana"]]
    s.merge(rs, on="CD_SETOR", how="left").to_file(DATA / "setores_manaus.gpkg", driver="GPKG")

    b = gpd.read_file(DATA / "bairros_manaus.geojson")
    b = b.drop(columns=[c for c in b.columns if c.startswith("bairro_")], errors="ignore")
    rb = _renda_csv("bairros")[["CD_BAIRRO", "responsaveis", "renda_media", "renda_mediana"]]
    rb.columns = ["CD_BAIRRO", "bairro_responsaveis", "bairro_renda_media", "bairro_renda_mediana"]
    b = b.merge(rb, on="CD_BAIRRO", how="left")
    b.to_file(DATA / "bairros_manaus.geojson", driver="GeoJSON")
    ss = s.merge(rs, on="CD_SETOR", how="left")
    return {"bairros_com_renda": int(b.bairro_renda_media.notna().sum()), "bairros": len(b),
            "setores_com_renda": int(ss.renda_media.notna().sum()), "setores": len(ss)}


DOM1_URL = AGREG_URL.replace("basico_BR_20260520", "caracteristicas_domicilio1_BR")
DOM2_URL = AGREG_URL.replace("basico_BR_20260520", "caracteristicas_domicilio2_BR_20250417")
# Dicionário IBGE, domicílios particulares permanentes ocupados (DPPO). Denominador = V00001 (DPPO do setor):
# validado, onde as categorias do tema estão completas a soma é igual a V00001 em 100% dos setores de Manaus.
# Numerador = única categoria "adequada" conhecida; categorias com 'X' (sigilo) não são somadas nem tratadas como 0.
SANEAMENTO = {"agua": "V00111",    # abastecimento por rede geral de distribuição
              "esgoto": "V00309",  # esgoto do banheiro em rede geral ou pluvial (fossa ligada à rede NÃO incluída)
              "lixo": "V00397"}    # lixo coletado no domicílio por serviço de limpeza (caçamba NÃO incluída)


def ingest_saneamento() -> dict:
    """Água, esgoto e lixo por setor (Censo 2022) + agregação exata por bairro (contagens são aditivas).

    Setor com numerador 'X'/ausente fica fora do tema (NaN, nunca zero) e fora do denominador do tema.
    `dppo_total` guarda todos os domicílios do setor para calcular a cobertura de dados do bairro/área.
    """
    import zipfile

    import pandas as pd

    s = gpd.read_file(DATA / "setores_manaus.gpkg")
    s = s.drop(columns=[c for c in s.columns if c.startswith(("agua_", "esgoto_", "lixo_", "dppo_"))])

    def read(url, name, key, cols):
        z = zipfile.ZipFile(_download(url, RAW / name))
        with z.open(z.namelist()[0]) as f:
            d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, usecols=[key, *cols]).rename(columns={key: "CD_SETOR"})
        d = d[d.CD_SETOR.isin(s.CD_SETOR)].copy()
        for c in cols:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        return d

    d1 = read(DOM1_URL, "domicilio1.zip", "CD_setor", ["V00001"]).rename(columns={"V00001": "dppo_total"})
    d2 = read(DOM2_URL, "domicilio2.zip", "setor", list(SANEAMENTO.values()))
    m = d1.merge(d2, on="CD_SETOR", how="left")
    out = m[["CD_SETOR", "dppo_total"]].copy()
    for tema, col in SANEAMENTO.items():
        ok = m[col].notna() & m.dppo_total.notna()
        out[f"{tema}_adequado"] = m[col].where(ok)
        out[f"{tema}_total"] = m.dppo_total.where(ok)
    s = s.merge(out, on="CD_SETOR", how="left")
    s.to_file(DATA / "setores_manaus.gpkg", driver="GPKG")

    b = gpd.read_file(DATA / "bairros_manaus.geojson")
    b = b.drop(columns=[c for c in b.columns if c.startswith(("agua_", "esgoto_", "lixo_", "dppo_"))])
    agg = s.groupby("CD_BAIRRO")[[c for c in out.columns if c != "CD_SETOR"]].sum(min_count=1).reset_index()
    b.merge(agg, on="CD_BAIRRO", how="left").to_file(DATA / "bairros_manaus.geojson", driver="GeoJSON")
    return {t: {"setores_validos": int(s[f"{t}_total"].notna().sum()), "de": len(s),
                "cobertura_dppo_pct": round(100 * s[f"{t}_total"].sum() / s.dppo_total.sum(), 1)} for t in SANEAMENTO}


ENTORNO_URL = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_"
               "Caracteristicas_urbanisticas_do_entorno_dos_domicilios/Agregados_por_Setor_csv/"
               "Agregados_por_setores_entorno_domic%c3%adlios_BR.zip")
# Entorno dos domicílios (face de quadra). Tema → (colunas "sim", colunas do denominador). V05000 = domicílios no setor
# com entorno levantado; em Manaus as categorias somam V05000 (validado). "Não declarado" fica fora do denominador.
ENTORNO = {
    "pav": (["V05006"], ["V05006", "V05007"]),                                   # via pavimentada
    "bueiro": (["V05009"], ["V05009", "V05010"]),                                # bueiro/boca de lobo
    "ilum": (["V05012"], ["V05012", "V05013"]),                                  # iluminação pública
    "onibus": (["V05015"], ["V05015", "V05016"]),                                # ponto de ônibus na face
    "calcada": (["V05021"], ["V05021", "V05022"]),                               # calçada
    "rampa": (["V05027"], ["V05027", "V05028"]),                                 # rampa para cadeirante
    "arvore": (["V05031", "V05032", "V05033"], ["V05030", "V05031", "V05032", "V05033"]),  # ≥1 árvore na face
}


def ingest_entorno() -> dict:
    """Infraestrutura urbana do entorno por setor + agregação exata por bairro. 'X'/ausente → NaN (nunca zero)."""
    import zipfile

    import pandas as pd

    pref = tuple(f"{t}_" for t in ENTORNO)
    s = gpd.read_file(DATA / "setores_manaus.gpkg")
    s = s.drop(columns=[c for c in s.columns if c.startswith(pref)])
    cols = sorted({c for a, b in ENTORNO.values() for c in (*a, *b)})
    z = zipfile.ZipFile(_download(ENTORNO_URL, RAW / "entorno_dom.zip"))
    with z.open(z.namelist()[0]) as f:
        d = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, usecols=["CD_setor", *cols]).rename(columns={"CD_setor": "CD_SETOR"})
    d = d[d.CD_SETOR.isin(s.CD_SETOR)].copy()
    for c in cols:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    out = pd.DataFrame({"CD_SETOR": d.CD_SETOR})
    for t, (sim, tot) in ENTORNO.items():
        ok = d[tot].notna().all(axis=1)
        out[f"{t}_adequado"] = d[sim].sum(axis=1).where(ok)
        out[f"{t}_total"] = d[tot].sum(axis=1).where(ok)
    s = s.merge(out, on="CD_SETOR", how="left")
    s.to_file(DATA / "setores_manaus.gpkg", driver="GPKG")

    b = gpd.read_file(DATA / "bairros_manaus.geojson")
    b = b.drop(columns=[c for c in b.columns if c.startswith(pref)])
    agg = s.groupby("CD_BAIRRO")[[c for c in out.columns if c != "CD_SETOR"]].sum(min_count=1).reset_index()
    b.merge(agg, on="CD_BAIRRO", how="left").to_file(DATA / "bairros_manaus.geojson", driver="GeoJSON")
    return {t: {"setores_validos": int(s[f"{t}_total"].notna().sum()), "de": len(s),
                "cobertura_dppo_pct": round(float(100 * s[f"{t}_total"].sum() / s.dppo_total.sum()), 1)} for t in ENTORNO}


def ingest_indicators() -> dict:
    out = {"fetched_at": now(), "ibge": {}, "bcb": {}}
    r = httpx.get(SIDRA, timeout=60).raise_for_status().json()[0]
    serie = r["resultados"][0]["series"][0]["serie"]
    out["ibge"]["populacao_manaus"] = {
        "valor": int(serie["2022"]), "unidade": "pessoas", "referencia": "2022",
        "escala": "município", "fonte": "IBGE Censo 2022, SIDRA agregado 4714 var. 93",
    }
    for code, nome in BCB_SERIES.items():
        pts = httpx.get(BCB.format(code, 12), timeout=60).raise_for_status().json()
        out["bcb"][str(code)] = {
            "nome": nome, "escala": "Brasil (contexto, não atribuível a bairro)",
            "fonte": f"BCB SGS série {code}", "pontos": pts,
        }
    (DATA / "indicadores.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print("bairros:", ingest_bairros())
    print("setores:", ingest_setores())
    print("renda:", ingest_renda())
    print("saneamento:", ingest_saneamento())
    print("entorno:", ingest_entorno())
    d = ingest_indicators()
    print("pop Manaus:", d["ibge"]["populacao_manaus"]["valor"], "| séries BCB:", list(d["bcb"]))
