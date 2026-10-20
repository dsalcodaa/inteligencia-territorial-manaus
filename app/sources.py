"""Catálogo de fontes e estado da integração (verificado por HTTP em 2026-10-20)."""

FUNCIONANDO, CREDENCIAIS, AUTORIZACAO, MANUAL, INDISPONIVEL = (
    "funcionando", "aguardando_credenciais", "aguardando_autorizacao", "importacao_manual", "indisponivel")

SOURCES = [
    dict(nome="IBGE — Malha de bairros Censo 2022 (AM)", url="https://geoftp.ibge.gov.br/", tipo="polígonos",
         cobertura="AM", licenca="Dados abertos IBGE (citar fonte)", estado=FUNCIONANDO,
         nota="Delimitação estatística; usada no MVP para Manaus (63 bairros)."),
    dict(nome="IBGE — SIDRA/Agregados (população)", url="https://servicodados.ibge.gov.br/api/docs/", tipo="tabular",
         cobertura="município", licenca="Dados abertos IBGE", estado=FUNCIONANDO,
         nota="Só população municipal carregada; sem indicadores por bairro ainda."),
    dict(nome="IBGE — Setores censitários 2022", url="https://geoftp.ibge.gov.br/", tipo="polígonos",
         cobertura="AM", licenca="Dados abertos IBGE", estado=FUNCIONANDO,
         nota="Carregados para Manaus: pessoas, domicílios, sexo, idade e renda do responsável (setor e bairro). Água, esgoto, lixo e infraestrutura do entorno (pavimentação, iluminação, calçada etc.) por setor e bairro. Pendente: cor/raça, alfabetização."),
    dict(nome="Banco Central — SGS", url="https://dadosabertos.bcb.gov.br/", tipo="séries",
         cobertura="Brasil", licenca="Dados abertos", estado=FUNCIONANDO,
         nota="Contexto macroeconômico; não atribuível a bairro."),
    dict(nome="SUFRAMA — dados abertos/indicadores", url="https://www.gov.br/suframa/pt-br/acesso-a-informacao/dados-abertos/base-de-dados",
         tipo="tabular", cobertura="PIM", licenca="a confirmar por arquivo", estado=MANUAL,
         nota="Páginas acessíveis; conjuntos não analisados ainda."),
    dict(nome="Transparência Fiscal AM", url="https://www.transparenciafiscal.am.gov.br/transparencia", tipo="tabular",
         cobertura="AM", licenca="a confirmar", estado=AUTORIZACAO, nota="Sem API visível; importar arquivos."),
    dict(nome="ZAP Imóveis", url="https://www.zapimoveis.com.br/", tipo="anúncios", cobertura="BR",
         licenca="Termos comerciais; sem scraping", estado=AUTORIZACAO, nota="Aceitar planilha licenciada."),
    dict(nome="Chaves na Mão", url="https://www.chavesnamao.com.br/imoveis/am-manaus/", tipo="anúncios", cobertura="BR",
         licenca="Termos vedam scraping", estado=AUTORIZACAO, nota="Aceitar planilha licenciada."),
    dict(nome="Google Places / Maps", url="https://developers.google.com/maps/documentation/places/web-service/overview",
         tipo="POIs", cobertura="global", licenca="ToS Google (cache/armazenamento restritos)", estado=CREDENCIAIS,
         nota="Requer chave e faturamento; manter separado das bases próprias."),
    dict(nome="dados.gov.br", url="https://dados.gov.br/", tipo="catálogo", cobertura="BR",
         licenca="variável", estado=CREDENCIAIS, nota="API respondeu 401 sem token."),
    dict(nome="OpenStreetMap (Overpass) — estabelecimentos", url="https://overpass-api.de/", tipo="POIs", cobertura="Manaus",
         licenca="ODbL (atribuição obrigatória)", estado=FUNCIONANDO,
         nota="~3,5 mil pontos em 27 categorias. Instável (502/429): ingestão com retentativa. Cobertura parcial: subestima a oferta real."),
    dict(nome="OpenStreetMap (Overpass) — vias, transporte e edificações", url="https://overpass-api.de/", tipo="linhas/pontos/polígonos",
         cobertura="Manaus", licenca="ODbL (atribuição obrigatória)", estado=FUNCIONANDO,
         nota="Vias até 'tertiary' (3,3 mil trechos), 314 pontos de ônibus, portos/terminais, 383 edificações/terrenos "
              "comerciais-industriais. Não são anúncios nem têm preço. Ruas locais não carregadas."),
    dict(nome="IBGE — CNEFE Censo 2022 (endereços)", url="https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/",
         tipo="pontos de endereço", cobertura="Manaus", licenca="Dados abertos IBGE (citar fonte)", estado=FUNCIONANDO,
         nota="878 mil registros (737 mil domicílios; conferem com o Censo em −0,5%). Só categoria e coordenada são guardadas "
              "(sem rua, número ou nome — LGPD). Retrato de 2022; 'outras finalidades' mistura comércio, serviços e indústria."),
    dict(nome="Imóveis — planilhas autorizadas (importação)", url="/api/imoveis/importar", tipo="anúncios", cobertura="Manaus",
         licenca="definida por lote importado", estado=MANUAL,
         nota="Importação validada (CSV/XLSX), exige ADMIN_TOKEN. Nenhum dado real carregado; só demo fictício, excluído por padrão."),
]
