"""Gera versões Word (.docx) do relatório completo e do relatório só de erros."""
import json
import os

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

from .resultado import ROTEIRO, OK, FALHA, AVISO, MANUAL, NA
from .relatorio import _diagnostico

COR = {OK: "1A7F37", FALHA: "CF222E", AVISO: "9A6700", MANUAL: "0969DA", NA: "6E7781"}
FUNDO = {OK: "DAFBE1", FALHA: "FFEBE9", AVISO: "FFF8C5", MANUAL: "DDF4FF", NA: "F6F8FA"}


# ----------------------------------------------------------------------------- helpers
def _doc(titulo):
    d = Document()
    s = d.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin = s.right_margin = Cm(1.8)
    s.top_margin = s.bottom_margin = Cm(1.8)
    st = d.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    for nome, tam in (("Title", 22), ("Heading 1", 15), ("Heading 2", 12.5), ("Heading 3", 11)):
        h = d.styles[nome]
        h.font.name = "Calibri"
        h.font.size = Pt(tam)
        h.font.color.rgb = RGBColor(0x1F, 0x23, 0x28)
        h.paragraph_format.keep_with_next = True
        h.paragraph_format.space_before = Pt(12 if nome != "Title" else 0)
        h.paragraph_format.space_after = Pt(4)
    d.core_properties.title = titulo
    # o modelo padrão do python-docx traz <w:zoom> sem 'percent' (inválido no schema)
    for z in d.settings.element.findall(qn("w:zoom")):
        z.set(qn("w:percent"), "100")
    # rodapé com número de página
    p = s.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _campo(p, "PAGE")
    return d


def _campo(par, instr):
    r = par.add_run()
    for tipo, txt in (("begin", None), (None, instr), ("end", None)):
        if tipo:
            e = OxmlElement("w:fldChar")
            e.set(qn("w:fldCharType"), tipo)
        else:
            e = OxmlElement("w:instrText")
            e.set(qn("xml:space"), "preserve")
            e.text = txt
        r._r.append(e)


def _sombra(cel, cor):
    tcPr = cel._tc.get_or_add_tcPr()
    for antigo in tcPr.findall(qn("w:shd")):  # evita <w:shd> duplicado (inválido no schema)
        tcPr.remove(antigo)
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), cor)
    tcPr.append(sh)


def _larguras(tabela, cms):
    tabela.autofit = False
    for row in tabela.rows:
        for c, w in zip(row.cells, cms):
            c.width = Cm(w)


def _cabecalho_repetido(linha):
    trPr = linha._tr.get_or_add_trPr()
    e = OxmlElement("w:tblHeader")
    e.set(qn("w:val"), "true")
    trPr.append(e)


def _tabela(d, cabecalho, larguras):
    t = d.add_table(rows=1, cols=len(cabecalho))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, txt in zip(t.rows[0].cells, cabecalho):
        c.text = ""
        r = c.paragraphs[0].add_run(txt)
        r.bold = True
        _sombra(c, "E8EBEF")
    _cabecalho_repetido(t.rows[0])
    _larguras(t, larguras)
    return t


def _status_cel(cel, st):
    cel.text = ""
    r = cel.paragraphs[0].add_run(st)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(COR.get(st, "000000"))
    _sombra(cel, FUNDO.get(st, "FFFFFF"))


def _detalhes(cel, detalhes, so_problemas=False):
    cel.text = ""
    primeiro = True
    for x in detalhes:
        if x.startswith("ℹ") and "JavaScript" in x:
            continue
        ruim = x[:1] in "✘⚠👁"
        if so_problemas and not ruim and not x.startswith("✔"):
            pass
        p = cel.paragraphs[0] if primeiro else cel.add_paragraph()
        primeiro = False
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run(x)
        r.font.size = Pt(9)
        if ruim:
            r.bold = True
            r.font.color.rgb = RGBColor.from_string(COR[FALHA] if x.startswith("✘") else COR[AVISO])


def _prints(d, pasta, item, largura_cm=16.5, max_prints=None):
    lista = item.get("prints") or []
    if max_prints:
        lista = lista[:max_prints]
    for rel in lista:
        caminho = os.path.join(pasta, rel)
        if not os.path.exists(caminho):
            continue
        try:
            img = _reduzir(caminho)
            d.add_picture(img, width=Cm(largura_cm))
            cap = d.add_paragraph(os.path.basename(rel))
            cap.runs[0].font.size = Pt(8)
            cap.runs[0].font.color.rgb = RGBColor(0x6E, 0x77, 0x81)
        except Exception:
            pass


def _reduzir(caminho, max_altura=2200):
    """Prints de página inteira podem ser muito altos: corta o topo (parte mais relevante)
    e reduz para manter o .docx leve."""
    from PIL import Image
    import io
    im = Image.open(caminho).convert("RGB")
    if im.height > max_altura:
        im = im.crop((0, 0, im.width, max_altura))
    if im.width > 1200:
        im = im.resize((1200, int(im.height * 1200 / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    buf.seek(0)
    return buf


def _resumo(d, itens):
    cont = {k: sum(i["status"] == k for i in itens) for k in (OK, FALHA, AVISO, MANUAL, NA)}
    t = _tabela(d, list(cont.keys()) + ["Total"], [2.9] * 6)
    row = t.add_row().cells
    for c, (k, v) in zip(row, cont.items()):
        _status_cel(c, str(v))
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(COR[k])
        c.paragraphs[0].runs[0].font.size = Pt(16)
        _sombra(c, FUNDO[k])
    row[-1].text = str(len(itens))
    row[-1].paragraphs[0].runs[0].font.size = Pt(16)
    row[-1].paragraphs[0].runs[0].bold = True
    _larguras(t, [2.9] * 6)


def _meta(d, dados):
    m = dados["meta"]
    p = d.add_paragraph()
    for rot, val in (("Ambiente", dados["ambiente"]), ("URL", m.get("url", "")), ("Curso (id)", m.get("curso_id", "")),
                     ("Estudante", m.get("modo_aluno", "")), ("Execução", m.get("data", "")),
                     ("Duração", f"{dados.get('duracao_s', 0):.0f} s")):
        r = p.add_run(f"{rot}: ")
        r.bold = True
        p.add_run(f"{val}    ")


# ----------------------------------------------------------------------------- relatório completo
def word_relatorio(pasta):
    with open(os.path.join(pasta, "resultados.json"), encoding="utf-8") as f:
        dados = json.load(f)
    itens = dados["itens"]
    d = _doc("Relatório de testes do Moodle")
    d.add_heading(f"Relatório de testes do Moodle — ambiente {dados['ambiente']}", 0)
    _meta(d, dados)
    d.add_heading("Resumo", 1)
    _resumo(d, itens)

    d.add_heading("Resultado por item do roteiro", 1)
    t = _tabela(d, ["Item", "Descrição", OK, FALHA, AVISO, "Outros"], [1.4, 7.6, 1.8, 1.8, 1.8, 1.8])
    por = {}
    for i in itens:
        por.setdefault(i["codigo"], []).append(i)
    codigos = sorted(por, key=lambda k: (k.startswith("X"), k))
    for cod in codigos:
        row = t.add_row().cells
        row[0].text, row[1].text = cod, ROTEIRO.get(cod, "")
        for c, st in zip(row[2:5], (OK, FALHA, AVISO)):
            n = sum(i["status"] == st for i in por[cod])
            c.text = str(n)
            if n and st != OK:
                _status_cel(c, str(n))
                c.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(COR[st])
                _sombra(c, FUNDO[st])
        row[5].text = str(sum(i["status"] in (MANUAL, NA) for i in por[cod]))
    _larguras(t, [1.4, 7.6, 1.8, 1.8, 1.8, 1.8])

    for cod in codigos:
        d.add_heading(f"{cod} — {ROTEIRO.get(cod, '')}", 1)
        t = _tabela(d, ["Verificação", "Papel", "Resultado", "Detalhes"], [4.6, 2.0, 2.3, 8.5])
        for i in por[cod]:
            row = t.add_row().cells
            row[0].text = i["titulo"]
            row[1].text = i["papel"]
            _status_cel(row[2], i["status"])
            _detalhes(row[3], i["detalhes"])
        _larguras(t, [4.6, 2.0, 2.3, 8.5])
        # evidências: prints das falhas/avisos (os de sucesso ficam no relatório HTML)
        com_print = [i for i in por[cod] if i.get("prints") and i["status"] in (FALHA, AVISO)]
        if com_print:
            d.add_heading("Evidências (falhas e avisos)", 3)
            for i in com_print:
                d.add_paragraph(f"{i['titulo']} ({i['papel']})").runs[0].bold = True
                _prints(d, pasta, i, max_prints=2)

    destino = os.path.join(pasta, "relatorio.docx")
    d.save(destino)
    return destino


# ----------------------------------------------------------------------------- só erros
def word_erros(pasta):
    with open(os.path.join(pasta, "resultados.json"), encoding="utf-8") as f:
        dados = json.load(f)
    itens = dados["itens"]
    ruins = [i for i in itens if i["status"] in (FALHA, AVISO, MANUAL)]
    grupos = {}
    for i in ruins:
        grupos.setdefault(_diagnostico(i), []).append(i)
    ordem = sorted(grupos, key=lambda k: (-sum(x["status"] == FALHA for x in grupos[k]), -len(grupos[k])))

    d = _doc("Erros encontrados nos testes do Moodle")
    d.add_heading(f"Erros encontrados — ambiente {dados['ambiente']}", 0)
    _meta(d, dados)
    d.add_paragraph(f"{sum(i['status'] == FALHA for i in ruins)} falha(s), "
                    f"{sum(i['status'] == AVISO for i in ruins)} aviso(s) e "
                    f"{sum(i['status'] == MANUAL for i in ruins)} item(ns) para verificação manual, "
                    f"de {len(itens)} verificações.")

    d.add_heading("Resumo por causa provável", 1)
    t = _tabela(d, ["Causa provável", "Falhas", "Avisos", "Itens afetados", "Ação sugerida"],
                [3.2, 1.4, 1.4, 3.8, 7.6])
    for k in ordem:
        its = grupos[k]
        row = t.add_row().cells
        row[0].text = k[0]
        row[0].paragraphs[0].runs[0].bold = True
        nf = sum(i["status"] == FALHA for i in its)
        row[1].text = str(nf)
        if nf:
            _status_cel(row[1], str(nf))
        row[2].text = str(len(its) - nf)
        row[3].text = "\n".join(sorted({f"{i['codigo']} {ROTEIRO.get(i['codigo'], '')}" for i in its}))
        row[4].text = k[1]
    _larguras(t, [3.2, 1.4, 1.4, 3.8, 7.6])

    for k in ordem:
        d.add_heading(k[0], 1)
        p = d.add_paragraph(k[1])
        p.runs[0].italic = True
        for i in sorted(grupos[k], key=lambda i: (i["status"] != FALHA, i["codigo"])):
            d.add_heading(f"[{i['status']}] {i['titulo']}", 2)
            info = d.add_paragraph()
            info.add_run("Item do roteiro: ").bold = True
            info.add_run(f"{i['codigo']} — {ROTEIRO.get(i['codigo'], '')}    ")
            info.add_run("Papel: ").bold = True
            info.add_run(i["papel"])
            t = _tabela(d, ["Detalhes"], [17.4])
            _detalhes(t.add_row().cells[0], i["detalhes"])
            _larguras(t, [17.4])
            if i.get("url"):
                pu = d.add_paragraph(f"Página: {i['url']}")
                pu.runs[0].font.size = Pt(8)
                pu.runs[0].font.color.rgb = RGBColor(0x6E, 0x77, 0x81)
            _prints(d, pasta, i)

    destino = os.path.join(pasta, "erros.docx")
    d.save(destino)
    return destino
