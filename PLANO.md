# Plataforma de Inteligência Territorial — Plano (verificado em 2026-10-20)

## 1. Ambiente
| Item | Estado |
|---|---|
| Python 3.15, Node 24, Git | OK |
| Docker, PostgreSQL/PostGIS, GDAL | **ausentes** |
| Libs geo (geopandas, shapely, pyogrio, fastapi) | instaladas em `.venv`, testadas |
| Disco livre | 337 GB |

Consequência: MVP roda com SQLite + Shapely/GeoPandas, sem instalar nada. Camada de dados via SQLAlchemy;
`DATABASE_URL` aponta para PostGIS (docker-compose incluído na Fase 2) sem mudar regra de negócio.

## 2. Matriz de integrações (testada por HTTP hoje)
| Fonte | Acesso verificado | Licença / limite | Estado |
|---|---|---|---|
| IBGE Localidades/Agregados (SIDRA) | 200; pop. Manaus 2022 = 2.063.689 (agregado 4714, var. 93) | Aberta, citar fonte | **Funcionando** (MVP) |
| IBGE Malhas — bairros Censo 2022 (AM) | GPKG 1,4 MB baixado; 476 bairros, 63 em Manaus; CRS 4674 | Aberta | **Funcionando** (MVP) |
| IBGE Malhas — setores censitários (AM) | Pasta `setores/gpkg/UF/AM/` existe | Aberta | Fase 1b (arquivo grande) |
| Banco Central SGS | 200 (série 432 Selic) | Aberta | **Funcionando** (MVP, só contexto nacional) |
| geotatica Plataforma_Dados | 200, 129 KB | Catálogo; usar só p/ descobrir fontes originais | Catálogo |
| SUFRAMA (dados abertos, indicadores) | 200 (páginas HTML) | Pública; datas/cobertura por arquivo a conferir | Importação manual (Fase 3) |
| Transparência Fiscal AM | 200, página de 1,2 KB (SPA, sem API visível) | A confirmar | Aguardando autorização / importação de arquivo |
| dados.gov.br API | 401 sem token | Token gratuito | Aguardando credenciais |
| OSM Nominatim | 200 | Política de uso: 1 req/s, sem bulk | Busca de endereço (MVP, uso leve) |
| OSM Overpass | 502 hoje | Instável | Fase 2 (usar extrato Geofabrik) |
| ZAP Imóveis | robots.txt 403 (bloqueia bots) | Sem scraping | **Aguardando autorização**; importar planilha licenciada |
| Chaves na Mão | robots.txt 200; termos vedam scraping | Sem scraping | **Aguardando autorização**; importar planilha |
| Google Places/Maps | Requer chave + faturamento | ToS restringe cache/armazenamento | **Aguardando credenciais**; isolado das bases próprias |

## 3. Arquitetura
- **Backend**: FastAPI, SQLAlchemy, GeoPandas/Shapely. Módulos: `sources/` (conectores), `analysis/`, `reports/`, `api/`.
- **Front**: Fase 1 = MapLibre GL JS + HTML/JS estático servido pelo FastAPI (sem build). Migrar para Next.js/React na Fase 4.
- **Dados**: toda tabela de indicador carrega `source_id`, `reference_date`, `spatial_scale`, `fetched_at`.
- **Relatório**: PDF via ReportLab + matplotlib.
- **Segurança**: segredos em `.env`; Google/chaves só no servidor; multi-tenant na Fase 4.

## 4. Escopo MVP (Fase 1)
1. Ingestão: bairros Manaus (IBGE), população município (SIDRA), séries BCB.
2. API: `/api/bairros`, `/api/area/summary` (polígono desenhado → bairros intersectados, área, população só na escala real disponível).
3. Mapa: camadas, desenho de polígono, clique com atributos, legenda, fontes.
4. PDF territorial com mapa, tabela, metodologia, fontes, datas, limitações.
5. Catálogo de fontes com estado.
6. Testes pytest das regras (interseção, rateio, ausência de dado ≠ zero).
7. Dados demo marcados **FICTÍCIO**.

Regra de integridade: população por bairro só entra quando vier de tabela do Censo 2022 por bairro; sem isso, mostrar "indisponível" — nunca ratear do município sem rotular como estimativa.

## 5. Modelo de dados (resumo)
`source`(id, nome, url, licença, estado, ref_date) · `territory`(id, nível, código_ibge, nome, geom) ·
`indicator`(id, territory_id, variável, valor, unidade, ref_date, source_id, escala) ·
`poi`(id, categoria, nome, geom, source_id) · `listing`(id, fonte, tipo, finalidade, preço, área, geom, coletado_em) ·
`study`/`project`/`org`/`user` (Fase 4).

## 6. Execução
```
cd %USERPROFILE%\projetos\plataforma-territorial
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.ingest      # baixa/normaliza dados
uvicorn app.main:app --reload
pytest
```
