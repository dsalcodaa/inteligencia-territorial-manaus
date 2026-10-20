"""Dados DEMONSTRATIVOS FICTÍCIOS de imóveis, só para testar a interface/validação. Uso: python -m app.demo

Valores, coordenadas e anúncios são inventados (semente fixa). NUNCA usar em estudos: ficam marcados demo=1.
"""
import numpy as np
import pandas as pd

from .analysis import DATA, load_bairros
from .imoveis import importar

ARQ = DATA / "demo" / "imoveis_demo_FICTICIO.csv"


def gerar() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    b = load_bairros()
    b = b[b.pessoas.fillna(0) > 20000].reset_index(drop=True)
    rows = []
    for i in range(160):
        r = b.iloc[rng.integers(len(b))]
        p = r.geometry.representative_point()
        fin = "venda" if i % 2 == 0 else "aluguel"
        area = float(rng.integers(40, 260))
        m2 = rng.normal(6500, 1800) if fin == "venda" else rng.normal(28, 8)
        rows.append({"id_anuncio": f"DEMO-{i:04d}", "finalidade": fin, "tipo": rng.choice(["apartamento", "casa", "comercial"]),
                     "preco": round(max(m2, 5) * area, 2), "area_m2": area, "quartos": int(rng.integers(1, 5)),
                     "vagas": int(rng.integers(0, 4)), "bairro": r.NM_BAIRRO,
                     "lat": round(p.y + rng.normal(0, 0.0005), 6), "lon": round(p.x + rng.normal(0, 0.0005), 6)})
    df = pd.DataFrame(rows)
    # linhas propositalmente inválidas, para exercitar a validação
    ruins = [{"id_anuncio": "DEMO-BAD1", "finalidade": "troca", "tipo": "casa", "preco": 1, "area_m2": 1},
             {"id_anuncio": "DEMO-BAD2", "finalidade": "venda", "tipo": "casa", "preco": 5000, "area_m2": 100},
             {"id_anuncio": "DEMO-BAD3", "finalidade": "venda", "tipo": "casa", "preco": 400000, "area_m2": 100, "lat": 10, "lon": 10}]
    return pd.concat([df, pd.DataFrame(ruins)], ignore_index=True)


if __name__ == "__main__":
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    df = gerar()
    df.to_csv(ARQ, index=False)
    res = importar(df, fonte="DEMO FICTÍCIO", licenca="dados inventados; uso apenas para teste", data_coleta="2026-01-01", demo=True)
    print(res["aceitos"], "aceitos;", res["rejeitados"])
