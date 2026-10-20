# Plataforma de Inteligência Territorial — Manaus

Plano, matriz de fontes e arquitetura: `PLANO.md`.

## Instalação e execução (Windows, PowerShell)
```
cd $HOME\projetos\plataforma-territorial
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app.ingest   # IBGE (bairros, setores, renda, saneamento, entorno) + BCB. Baixa ~250 MB na 1ª vez
.venv\Scripts\python -m app.pois     # estabelecimentos OSM, 27 categorias (Overpass; retenta em 429/502)
.venv\Scripts\python -m app.osm      # vias, transporte/infraestrutura e edificações não residenciais (OSM)
.venv\Scripts\python -c "from app.osm import ingest_vias_locais; print(ingest_vias_locais())"  # ruas locais (18,7 mil trechos; só métricas)
.venv\Scripts\python -m app.cnefe    # CNEFE Censo 2022 de Manaus (14,6 MB): endereços por tipo; guarda só categoria e coordenada
.venv\Scripts\python -m app.demo     # opcional: imóveis FICTÍCIOS (demo=1, fora dos indicadores por padrão)
.venv\Scripts\python -m uvicorn app.main:app
.venv\Scripts\python -m pytest
```
Abra http://127.0.0.1:8000.

## Variáveis de ambiente (apenas no servidor)
| Variável | Efeito |
|---|---|
| `ADMIN_TOKEN` | Habilita `POST /api/imoveis/importar` (header `X-Admin-Token`). Sem ela, a rota responde 403. |
| `GOOGLE_MAPS_API_KEY` | Ativa `app/google_places.py` (não testado: sem chave neste ambiente). |

## Importar imóveis (planilha autorizada)
Colunas obrigatórias: `finalidade` (venda|aluguel), `tipo` (apartamento|casa|terreno|comercial|galpao|outro), `preco`, `area_m2`.
Opcionais: `id_anuncio`, `url`, `bairro`, `lat`, `lon`, `quartos`, `vagas`, `data_coleta`. Formulário exige `fonte`, `licenca`, `data_coleta`.
Linhas inválidas são rejeitadas com motivo; nada é corrigido em silêncio. Preço = anunciado, não transacionado.

## CNEFE (endereços)
- Fonte: IBGE, Censo 2022. Rua, número, complemento, CEP e nome do estabelecimento **não são gravados** (LGPD); só coordenada e categoria.
- Espécies: domicílio, coletivo, ensino, saúde, religioso, agropecuário, em construção e "outras finalidades" (comércio + serviços + indústria, que o IBGE não separa).
- Segmentos de comércio/serviços (`app/segmentos.py`) são **indicativos**, por palavra-chave no nome; ~24% ficam "não classificado" e ~8% são "ponto vago/fechado".
- Contagens por área usam só coordenadas de endereço (níveis 1–3, 99,9% do total).

## Regras de integridade
- Dado ausente/sigiloso (`X`) vira vazio e é informado; nunca zero nem imputado.
- Valores de área desenhada usam rateio por área dos setores (faixa mínimo exato/estimativa).
- OSM é cobertura parcial: contagens são "mapeados no OSM", não oferta real.
- Dados Google nunca são persistidos nas bases próprias.
