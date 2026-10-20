# Fontes e licenças dos dados em `data/`

Os arquivos em `data/` são **derivados** de fontes abertas; os downloads brutos não são versionados (`data/raw/`).
Reproduza com `python -m app.ingest`, `python -m app.pois`, `python -m app.osm` e `python -m app.cnefe`.

| Arquivos | Fonte | Licença / condição |
|---|---|---|
| `bairros_manaus.geojson`, `setores_manaus.gpkg`, `indicadores.json` | IBGE (Censo 2022, malhas, SIDRA) e Banco Central (SGS) | Dados abertos; citar a fonte |
| `cnefe_manaus.npz/.json` | IBGE — CNEFE Censo 2022 | Dados abertos; citar a fonte. Só coordenada e categoria (sem rua, número, CEP ou nome do estabelecimento) |
| `pois_osm.gpkg`, `vias*_osm.gpkg`, `infra_osm.gpkg`, `edificacoes_osm.gpkg` | © OpenStreetMap contributors | **ODbL**: atribuição obrigatória e compartilhamento pela mesma licença para bases derivadas |
| `demo/imoveis_demo_FICTICIO.csv` | Gerado | **Fictício**; nunca usar em estudos |

Dados do Google Places, ZAP e Chaves na Mão **não** são armazenados aqui (termos de uso restringem cache/redistribuição).
