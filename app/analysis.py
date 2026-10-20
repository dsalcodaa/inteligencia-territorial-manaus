"""Análise espacial: área de estudo × bairros. Áreas calculadas em SIRGAS 2000 / UTM 20S (EPSG:31980)."""
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape

DATA = Path(__file__).resolve().parent.parent / "data"
METRIC_CRS = 31980
FAIXAS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-39", "40-49", "50-59", "60-69", "70+"]
DEMOG = ["homens", "mulheres", *[f"idade_{f}" for f in FAIXAS]]
# Definição exata de "adequado" (ver app/ingest.py): só categorias presentes no dado; fossa ligada à rede e caçamba ficam de fora.
SANEAMENTO = {"agua": "% de domicílios com abastecimento por rede geral",
              "esgoto": "% de domicílios com esgoto em rede geral ou pluvial",
              "lixo": "% de domicílios com lixo coletado no domicílio por serviço de limpeza"}
# Infraestrutura do entorno (face de quadra); % entre faces com resposta "sim" ou "não" (não declarado excluído).
ENTORNO = {"pav": "% de domicílios em face com via pavimentada",
           "bueiro": "% de domicílios em face com bueiro/boca de lobo",
           "ilum": "% de domicílios em face com iluminação pública",
           "onibus": "% de domicílios em face com ponto de ônibus",
           "calcada": "% de domicílios em face com calçada",
           "rampa": "% de domicílios em face com rampa para cadeirante",
           "arvore": "% de domicílios em face com ao menos 1 árvore"}
INDICADORES_DOM = {**SANEAMENTO, **ENTORNO}


def load_bairros() -> gpd.GeoDataFrame:
    return gpd.read_file(DATA / "bairros_manaus.geojson")


def load_indicators() -> dict:
    return json.loads((DATA / "indicadores.json").read_text(encoding="utf-8"))


def load_setores() -> gpd.GeoDataFrame:
    return gpd.read_file(DATA / "setores_manaus.gpkg")


_setores_cache: dict = {}


def _populacao(area_m, bairros) -> dict:
    """Pessoas na área: mínimo exato (setores inteiros) e estimativa (rateio por área nos setores cortados)."""
    if "s" not in _setores_cache:
        s = load_setores().to_crs(METRIC_CRS)
        _setores_cache["s"] = s
        _setores_cache["area"] = s.geometry.area
    s, s_area = _setores_cache["s"], _setores_cache["area"]
    hit = s.iloc[list(s.sindex.query(area_m, predicate="intersects"))]
    minimo = estimativa = 0.0
    sem_valor = 0
    demog = {c: 0.0 for c in DEMOG}
    renda_w = renda_sum = 0.0
    renda_sem = 0
    san = {t: [0.0, 0.0] for t in INDICADORES_DOM}
    san_dppo = 0.0
    for idx, row in hit.iterrows():
        if row.pessoas != row.pessoas:
            sem_valor += 1
            continue
        frac = row.geometry.intersection(area_m).area / s_area[idx]
        estimativa += row.pessoas * frac
        for c in DEMOG:
            if row[c] == row[c]:  # NaN ignorado, não vira zero
                demog[c] += row[c] * frac
        if frac >= 0.9999:
            minimo += row.pessoas
        if row.dppo_total == row.dppo_total:
            san_dppo += row.dppo_total * frac
        for t in INDICADORES_DOM:
            if row[f"{t}_total"] == row[f"{t}_total"]:
                san[t][0] += row[f"{t}_adequado"] * frac
                san[t][1] += row[f"{t}_total"] * frac
        if row.renda_media == row.renda_media and row.responsaveis == row.responsaveis:
            w = row.responsaveis * frac
            renda_w += w
            renda_sum += w * row.renda_media
        else:
            renda_sem += 1
    return {"minimo_exato": int(minimo), "estimativa": int(round(estimativa)), "setores_na_area": len(hit),
            "faixas_etarias": {c[6:]: int(round(demog[c])) for c in DEMOG if c.startswith("idade_")},
            **{grupo: {
                t: {"descricao": desc[t], "pct": round(100 * san[t][0] / san[t][1], 1) if san[t][1] else None,
                    "cobertura_dados_pct": round(100 * san[t][1] / san_dppo, 1) if san_dppo else None}
                for t in desc} for grupo, desc in (("saneamento", SANEAMENTO), ("infraestrutura", ENTORNO))},
            "renda_responsavel": {
                # média das médias dos setores ponderada por responsáveis×fração de área: aproximação, a mediana não é agregável
                "media_aprox_rs": round(renda_sum / renda_w, 2) if renda_w else None,
                "setores_sem_renda": renda_sem, "referencia": "2022 (rendimento nominal mensal, R$)",
                "fonte": "IBGE Censo 2022, Rendimento do Responsável (V06004), escala setor"},
            "sexo": {"homens": int(round(demog["homens"])), "mulheres": int(round(demog["mulheres"]))},
            "setores_sem_valor": sem_valor, "fonte": "IBGE Censo 2022, agregados por setor (v0001)",
            "escala": "setor censitário", "referencia": "2022"}


def summarize(geojson_geom: dict, bairros: gpd.GeoDataFrame | None = None) -> dict:
    """Bairros que intersectam o polígono, com área e fração coberta.

    População por bairro NÃO é estimada: o MVP só tem população municipal (ver `limitacoes`).
    """
    bairros = load_bairros() if bairros is None else bairros
    area = gpd.GeoSeries([shape(geojson_geom)], crs=4326).to_crs(METRIC_CRS)
    if not area.iloc[0].is_valid:
        raise ValueError("polígono inválido")
    b = bairros.to_crs(METRIC_CRS)
    rows = []
    for (_, row), geom in zip(bairros.iterrows(), b.geometry):
        inter = geom.intersection(area.iloc[0])
        if inter.is_empty or inter.area == 0:
            continue
        rows.append({
            "codigo": row.CD_BAIRRO, "bairro": row.NM_BAIRRO,
            "area_bairro_km2": round(geom.area / 1e6, 3),
            "area_na_selecao_km2": round(inter.area / 1e6, 3),
            "pct_do_bairro": round(100 * inter.area / geom.area, 1),
        })
    rows.sort(key=lambda r: -r["area_na_selecao_km2"])
    pop = _populacao(area.iloc[0], bairros)
    pessoas_bairro = bairros.set_index("CD_BAIRRO").pessoas
    for r in rows:
        v = pessoas_bairro.get(r["codigo"])
        r["populacao_bairro"] = None if v is None or v != v else int(v)
        bi = bairros.set_index("CD_BAIRRO")
        for t in INDICADORES_DOM:
            num, tot = bi[f"{t}_adequado"].get(r["codigo"]), bi[f"{t}_total"].get(r["codigo"])
            r[f"{t}_pct"] = round(100 * num / tot, 1) if tot == tot and tot else None
        for k in ("renda_media", "renda_mediana"):
            x = bairros.set_index("CD_BAIRRO")[f"bairro_{k}"].get(r["codigo"])
            r[f"bairro_{k}"] = None if x is None or x != x else float(x)
    return {
        "area_selecao_km2": round(area.iloc[0].area / 1e6, 3),
        "bairros": rows,
        "populacao_selecao": pop,
        "limitacoes": [
            "População da seleção: setores totalmente dentro da área são contagem exata do Censo 2022; "
            "setores cortados pela borda são rateados por área (supõe distribuição uniforme no setor) — por isso "
            "o resultado é uma faixa [mínimo, estimativa].",
            "Renda da seleção: média dos setores ponderada por responsáveis e área (aproximação); a mediana não pode ser "
            "agregada, por isso só aparece por bairro (valor oficial IBGE). Renda = rendimento do responsável pelo domicílio, "
            "não renda per capita; base: responsáveis em domicílios particulares permanentes ocupados.",
            "Setores sem bairro atribuído pelo IBGE (áreas rurais) entram na população da seleção, mas não na tabela de bairros.",
            "Limites de bairros: IBGE Censo 2022, delimitação para fins estatísticos, não oficial municipal.",
        ],
    }
