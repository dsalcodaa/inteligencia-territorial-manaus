"""PDF de diagnóstico territorial preliminar."""
import io
import math
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from shapely.geometry import shape

from . import cnefe, ponto
from .acessibilidade import acessibilidade
from .analysis import load_bairros, load_indicators, summarize
from .concorrencia import concorrencia
from .sources import SOURCES


def _br(n) -> str:
    """Número com ponto de milhar (pt-BR). Formata só o número: nunca aplicar replace em frases."""
    return f"{n:,.0f}".replace(",", ".")


def _map_png(geom: dict, bairros, emp: dict | None = None) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7, 5))
    bairros.plot(ax=ax, color="#e8ecef", edgecolor="#9aa5ad", linewidth=0.4)
    sel = shape(geom)
    for poly in getattr(sel, "geoms", [sel]):  # Polygon ou MultiPolygon (bairros escolhidos)
        xs, ys = poly.exterior.xy
        ax.fill(xs, ys, color="#1f6feb", alpha=0.35)
        ax.plot(xs, ys, color="#1f6feb", linewidth=1.5)
    if emp:
        ax.plot(emp["lon"], emp["lat"], marker="*", color="#dc2626", markersize=14, markeredgecolor="white", zorder=5)
    # enquadra a seleção (com folga) para que círculos pequenos fiquem visíveis
    minx, miny, maxx, maxy = sel.bounds
    mx, my = max((maxx - minx) * .6, .02), max((maxy - miny) * .6, .02)
    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_aspect(1 / math.cos(math.radians((miny + maxy) / 2)))  # corrige a distorção de lon/lat
    ax.set_axis_off()
    ax.set_title("Área de estudo sobre bairros de Manaus (IBGE 2022)", fontsize=9)
    ax.annotate("N ↑", (0.95, 0.93), xycoords="axes fraction", fontsize=10, ha="center")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_pdf(geom: dict, titulo: str = "Diagnóstico territorial preliminar", categoria: str | None = None,
              empreendimento: dict | None = None) -> bytes:
    emp = empreendimento
    if emp:
        titulo = f"Estudo de localização — {emp['nome']}"
    bairros = load_bairros()
    s = summarize(geom, bairros)
    ind = load_indicators()
    pop = ind["ibge"]["populacao_manaus"]
    ps = s["populacao_selecao"]
    st = getSampleStyleSheet()
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=titulo)
    el = [Paragraph(titulo, st["Title"]), Paragraph(f"Gerado em {date.today():%d/%m/%Y}", st["Normal"]), Spacer(1, 12)]

    if emp:
        b = emp["bairro"]
        el += [Paragraph("Empreendimento analisado", st["Heading2"]),
               Paragraph(f"<b>{emp['nome']}</b> · coordenadas {emp['lat']:.5f}, {emp['lon']:.5f} · bairro: "
                         f"<b>{b['nome'] if b else 'fora dos limites de bairros do IBGE'}</b>"
                         + (f" (população {_br(b['populacao'])}" + (f", renda mediana do responsável R$ {_br(b['renda_mediana'])}" if b['renda_mediana'] else "") + ")" if b else "")
                         + f". Área de influência: círculo de {_br(emp['raio_m'])} m de raio em linha reta, "
                         "que não equivale a tempo nem rota de deslocamento.", st["Normal"])]

    el += [Paragraph("1. Sumário", st["Heading2"]),
           Paragraph(f"A área selecionada mede {s['area_selecao_km2']:.2f} km² e intersecta {len(s['bairros'])} bairro(s). "
                     f"População estimada na área: <b>{_br(ps['estimativa'])}</b> (mínimo exato {_br(ps['minimo_exato'])}), "
                     f"Censo {ps['referencia']}, escala {ps['escala']}. "
                     f"População total de Manaus (SIDRA, escala {pop['escala']}): {_br(pop['valor'])}.", st["Normal"]),
           Spacer(1, 8), Image(_map_png(geom, bairros, emp), width=16 * cm, height=11.4 * cm)]

    fig, ax = plt.subplots(figsize=(7, 2.6))
    ax.bar(list(ps["faixas_etarias"]), list(ps["faixas_etarias"].values()), color="#1f6feb")
    ax.set_title("População estimada por faixa etária (Censo 2022, setores)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    el += [Spacer(1, 6), Image(buf, width=15 * cm, height=5.6 * cm),
           Paragraph(f"Mulheres {ps['sexo']['mulheres']:,} · Homens {ps['sexo']['homens']:,} (estimativa).".replace(",", "."), st["Normal"])]

    rr = ps["renda_responsavel"]
    if rr["media_aprox_rs"] is not None:
        el.append(Paragraph(
            f"Renda nominal média mensal do responsável pelo domicílio (aprox.): <b>R$ {rr['media_aprox_rs']:,.0f}</b>".replace(",", ".")
            + f" — {rr['setores_sem_renda']} setor(es) sem dado (sigilo). Não é renda per capita nem renda domiciliar.", st["Normal"]))

    el += [Paragraph("Saneamento básico dos domicílios (Censo 2022)", st["Heading2"])]
    for t, v in ps["saneamento"].items():
        el.append(Paragraph(f"• {v['descricao']}: <b>{v['pct']}%</b> (dados disponíveis para {v['cobertura_dados_pct']}% dos domicílios; "
                            "setores com sigilo estatístico 'X' excluídos, não tratados como zero).", st["Normal"]))

    el += [Paragraph("Infraestrutura urbana do entorno dos domicílios (Censo 2022)", st["Heading2"])]
    for t, v in ps["infraestrutura"].items():
        el.append(Paragraph(f"• {v['descricao']}: <b>{v['pct']}%</b> (dados para {v['cobertura_dados_pct']}% dos domicílios).", st["Normal"]))
    el.append(Paragraph("Atributos observados na face de quadra do domicílio; \"ponto de ônibus\" indica presença na própria face, "
                        "não proximidade ou qualidade do transporte. Respostas \"não declarado\" ficam fora do cálculo.", st["Normal"]))

    el += [Paragraph("2. Bairros na área", st["Heading2"])]
    rows = [["Bairro", "Área do bairro (km²)", "Na seleção (km²)", "% do bairro", "Pop. do bairro", "Renda mediana resp. (R$)", "Água %", "Esgoto %", "Lixo %"]] + [
        [b["bairro"], b["area_bairro_km2"], b["area_na_selecao_km2"], b["pct_do_bairro"],
         "n/d" if b["populacao_bairro"] is None else f"{b['populacao_bairro']:,}".replace(",", "."),
         "n/d" if b["bairro_renda_mediana"] is None else f"{b['bairro_renda_mediana']:,.0f}".replace(",", "."),
         *["n/d" if b[f"{t}_pct"] is None else b[f"{t}_pct"] for t in ("agua", "esgoto", "lixo")]]
        for b in s["bairros"][:25]]
    rows[0] = ["Bairro", "Área km²", "Seleção km²", "% bairro", "Pop.", "Renda med. R$", "Água %", "Esgoto %", "Lixo %"]
    t = Table(rows, repeatRows=1, colWidths=[3.6 * cm, 1.6 * cm, 2.1 * cm, 1.6 * cm, 1.7 * cm, 2.3 * cm, 1.4 * cm, 1.4 * cm, 1.3 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
    el += [t, Spacer(1, 8)]

    en = cnefe.analise(geom, (emp["lon"], emp["lat"]) if emp else None, ponto.raios_aneis(emp["raio_m"]) if emp else None)
    ce, bs = en["contagens"], en["baseline_manaus"]
    tot_b = max(1, bs["total"])
    el += [Paragraph("Endereços por tipo (CNEFE, Censo 2022)", st["Heading2"]),
           Paragraph(f"<b>{_br(ce['total'])}</b> endereços com coordenada na área. Fonte: {en['fonte']} (referência {en['referencia']}).", st["Normal"])]
    base_b = bs["por_especie"]
    linhas = [["Tipo de endereço", "Na área", "% da área", "% de Manaus"]] + [
        [cnefe.ESPECIES[k], _br(n), f"{100 * n / max(1, ce['total']):.1f}%".replace(".", ","), f"{100 * base_b[k] / tot_b:.1f}%".replace(".", ",")]
        for k, n in ce["por_especie"].items() if n or base_b[k]]
    t2 = Table(linhas, repeatRows=1, colWidths=[7.4 * cm, 2.6 * cm, 2.6 * cm, 2.9 * cm])
    t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    el += [Spacer(1, 4), t2, Spacer(1, 4),
           Paragraph("Moradia: " + " · ".join(f"{k} {_br(v)}" for k, v in ce["moradia"].items()) + ".", st["Normal"])]
    seg = {k: v for k, v in ce["segmentos"].items() if v}
    if seg:
        ordem = sorted(seg.items(), key=lambda kv: kv[1])
        fig, ax = plt.subplots(figsize=(7, 0.34 * len(ordem) + 0.8))
        ax.barh([k for k, _ in ordem], [v for _, v in ordem], color="#2a78d6", height=0.6)
        for i, (_, v) in enumerate(ordem):
            ax.text(v, i, f" {v}", va="center", fontsize=7)
        ax.set_title("Comércio, serviços e outras finalidades por segmento (indicativo)", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
        buf2 = io.BytesIO()
        fig.savefig(buf2, format="png", dpi=150, bbox_inches="tight")
        h = fig.get_size_inches()[1] / 7 * 15
        plt.close(fig)
        buf2.seek(0)
        el += [Spacer(1, 4), Image(buf2, width=15 * cm, height=h * cm)]
    el += [Paragraph("Interpretação", st["Heading3"])] + [Paragraph("• " + x, st["Normal"]) for x in en["interpretacao"]]
    if en.get("por_anel"):
        el += [Paragraph("A partir do empreendimento (acumulado, linha reta):", st["Normal"])]
        ta = Table([["Raio (m)", "Domicílios", "Comércio/serviços", "Ensino", "Saúde", "Religioso"]] +
                   [[_br(a["raio_m"]), _br(a["domicilios"]), _br(a["comercio_servicos"]), _br(a["ensino"]), _br(a["saude"]), _br(a["religioso"])]
                    for a in en["por_anel"]], repeatRows=1)
        ta.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (0, 0), (-1, -1), "RIGHT")]))
        el += [ta]
    el += [Paragraph("Limitações do CNEFE", st["Heading3"])] + [Paragraph("• " + x, st["Normal"]) for x in en["avisos"]]

    ac = acessibilidade(geom)
    fm = lambda v: "n/d" if v is None else f"{v['distancia_m']:,} m".replace(",", ".") + (f" ({v['nome']})" if v["nome"] else "")
    el += [Paragraph("Acessibilidade e infraestrutura (OpenStreetMap)", st["Heading2"]),
           Paragraph("Vias na área: " + (" · ".join(f"{k} {v} km" for k, v in ac["vias_km"].items()) or "nenhuma carregada")
                     + (f" · ruas locais {ac['vias_locais_km']} km" if ac["vias_locais_km"] is not None else "")
                     + f" — densidade total {ac['densidade_vias_km_por_km2']} km/km². Via arterial mais próxima do centro: {fm(ac['via_arterial_mais_proxima'])}. "
                     f"Pontos de ônibus na área: {ac['infra_na_area'].get('ponto_onibus', 0)}; mais próximo do centro: "
                     f"{fm(ac['mais_proximo_do_centro']['ponto_onibus'])}. Aeroporto: {fm(ac['mais_proximo_do_centro']['aeroporto'])}; "
                     f"porto/terminal fluvial: {fm(ac['mais_proximo_do_centro']['porto'])}.", st["Normal"]),
           Paragraph("Edificações não residenciais mapeadas: " + (" · ".join(f"{e['tipo']} {e['quantidade']}" for e in ac["edificacoes_nao_residenciais"]) or "nenhuma")
                     + f". {ac['nota_edificacoes']}", st["Normal"]),
           Paragraph(f"{ac['aviso']} Fonte: {ac['fonte']}; coletado em {ac['coletado_em']}.", st["Normal"])]

    if categoria:
        c = concorrencia(geom, categoria, (emp["lon"], emp["lat"]) if emp else None)
        f = lambda v: "n/d" if v is None else f"{v:,}".replace(",", ".")
        el += [Paragraph(f"Concorrência — {c['rotulo']}", st["Heading2"]),
               Paragraph(f"<b>{c['estabelecimentos_na_area']}</b> estabelecimentos mapeados no OpenStreetMap na área "
                         f"({c['por_km2']}/km²). Habitantes por estabelecimento: {f(c['hab_por_estabelecimento'])}; "
                         f"por 10 mil habitantes: {f(c['estab_por_10mil_hab'])}. Distância do centro ao mais próximo: "
                         f"{f(c['dist_centro_ao_mais_proximo_m'])} m; vizinho mais próximo médio: {f(c['vizinho_mais_proximo_medio_m'])} m.",
                         st["Normal"]),
               Paragraph(f"<b>Atenção:</b> {c['aviso']} Bairros populosos sem registro no OSM "
                         f"({len(c['bairros_sem_registro_osm'])}) provavelmente refletem mapeamento incompleto, não ausência de oferta. "
                         f"Fonte: {c['fonte']}; coletado em {c['coletado_em']}.", st["Normal"])]
        if c["do_ponto"]:
            dp = c["do_ponto"]
            el += [Paragraph("A partir do empreendimento (acumulado, linha reta): " +
                             " · ".join(f"até {a['raio_m']} m: {a['estabelecimentos']}" for a in dp["aneis"]) + ". Mais próximos: " +
                             "; ".join(f"{m['nome'] or '(sem nome no OSM)'} a {m['distancia_m']} m" for m in dp["mais_proximos"]) + ".",
                             st["Normal"])]

    el += [Paragraph("3. Contexto macroeconômico (Brasil)", st["Heading2"])]
    for code, serie in ind["bcb"].items():
        last = serie["pontos"][-1]
        el.append(Paragraph(f"{serie['nome']}: {last['valor']} em {last['data']} — {serie['escala']}.", st["Normal"]))

    el += [Paragraph("4. Metodologia", st["Heading2"]),
           Paragraph("Interseção do polígono com os limites de bairros do IBGE (Censo 2022). Áreas calculadas em "
                     "SIRGAS 2000 / UTM 20S (EPSG:31980). Valores da área (população, faixas etárias, renda, saneamento) vêm do rateio por "
                     "área dos setores censitários cortados pela borda; dado ausente ou sigiloso fica de fora e é informado, "
                     "nunca preenchido.", st["Normal"]),
           Paragraph("5. Limitações", st["Heading2"])]
    el += [Paragraph("• " + x, st["Normal"]) for x in s["limitacoes"]]
    el += [Paragraph("6. Fontes e datas", st["Heading2"]),
           Paragraph(f"• {pop['fonte']} (ref. {pop['referencia']}).", st["Normal"]),
           Paragraph(f"• {ps['fonte']} (ref. {ps['referencia']}). A soma dos setores de Manaus (2.068.939) difere em 0,25% "
                     "do total municipal do SIDRA (2.063.689); a divergência não foi reconciliada.", st["Normal"]),
           Paragraph(f"• Dados coletados em {ind['fetched_at']}.", st["Normal"])]
    el += [Paragraph(f"• {x['nome']} — {x['estado']}", st["Normal"]) for x in SOURCES if x["estado"] == "funcionando"]
    doc.build(el)
    return out.getvalue()
