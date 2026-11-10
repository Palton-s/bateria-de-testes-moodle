"""Gera o relatório HTML (um ambiente ou comparação antigo × novo)."""
import html
import json
import os
import time

from .resultado import ROTEIRO, OK, FALHA, AVISO, MANUAL, NA

COR = {OK: "#1a7f37", FALHA: "#cf222e", AVISO: "#9a6700", MANUAL: "#0969da", NA: "#6e7781"}

CSS = """
:root{--bg:#f6f8fa;--card:#fff;--tx:#1f2328;--mut:#59636e;--bd:#d1d9e0}
@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--card:#161b22;--tx:#e6edf3;--mut:#9198a1;--bd:#30363d}}
body{font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--tx);margin:0;padding:16px}
.wrap{max-width:1280px;margin:auto}
h1{margin:.2em 0}h2{margin-top:1.6em;border-bottom:1px solid var(--bd);padding-bottom:.3em}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px 16px;min-width:120px}
.card b{font-size:1.6em;display:block}
table{width:100%;border-collapse:collapse;background:var(--card);margin:8px 0}
td,th{border:1px solid var(--bd);padding:6px 8px;vertical-align:top;text-align:left;font-size:14px}
th{background:var(--bg)}
.st{font-weight:700;white-space:nowrap}
ul.det{margin:0;padding-left:18px}ul.det li{margin:2px 0}
.prints img{max-width:260px;max-height:170px;border:1px solid var(--bd);margin:4px 4px 0 0;cursor:zoom-in}
.mut{color:var(--mut);font-size:13px}
details summary{cursor:pointer}
.filtros button{margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--bd);border-radius:6px;background:var(--card);color:var(--tx);cursor:pointer}
@media (max-width:700px){td,th{font-size:12px}.prints img{max-width:140px}}
"""

JS = """
function filtrar(s){document.querySelectorAll('tr[data-st]').forEach(r=>{r.style.display=(!s||r.dataset.st===s)?'':'none'})}
"""


def _st(s):
    return f'<span class="st" style="color:{COR.get(s, "#000")}">{html.escape(s)}</span>'


def _prints(item, base_rel):
    if not item.get("prints"):
        return ""
    return '<div class="prints">' + "".join(
        f'<a href="{html.escape(os.path.join(base_rel, p).replace(os.sep, "/"))}" target="_blank">'
        f'<img loading="lazy" src="{html.escape(os.path.join(base_rel, p).replace(os.sep, "/"))}"></a>'
        for p in item["prints"]) + "</div>"


def _resumo(itens):
    c = {k: 0 for k in (OK, FALHA, AVISO, MANUAL, NA)}
    for i in itens:
        c[i["status"]] = c.get(i["status"], 0) + 1
    return c


def _cards(c):
    return '<div class="cards">' + "".join(
        f'<div class="card"><b style="color:{COR.get(k, "inherit")}">{v}</b>{html.escape(k)}</div>' for k, v in c.items()) + "</div>"


def relatorio_ambiente(pasta):
    with open(os.path.join(pasta, "resultados.json"), encoding="utf-8") as f:
        d = json.load(f)
    itens = d["itens"]
    c = _resumo(itens)
    partes = [f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
              f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
              f"<title>Testes Moodle - {html.escape(d['ambiente'])}</title><style>{CSS}</style><script>{JS}</script></head>"
              f"<body><div class='wrap'><h1>Testes do Moodle — ambiente <em>{html.escape(d['ambiente'])}</em></h1>"
              f"<div class='mut'>{html.escape(d['meta'].get('url', ''))} · curso {d['meta'].get('curso_id', '')} · "
              f"modo estudante: {html.escape(d['meta'].get('modo_aluno', ''))} · executado em "
              f"{html.escape(d['meta'].get('data', ''))} · duração {d['duracao_s']:.0f}s</div>",
              _cards(c),
              "<div class='filtros'>Filtrar: <button onclick=\"filtrar('')\">Todos</button>"
              + "".join(f"<button onclick=\"filtrar('{k}')\">{k}</button>" for k in (FALHA, AVISO, MANUAL, OK, NA))
              + "</div>"]
    por = {}
    for i in itens:
        por.setdefault(i["codigo"], []).append(i)
    for cod in sorted(por, key=lambda k: (k.startswith("X"), k)):
        partes.append(f"<h2>{cod} — {html.escape(ROTEIRO.get(cod, ''))}</h2><table><tr><th style='width:26%'>Verificação</th>"
                      f"<th style='width:9%'>Papel</th><th style='width:10%'>Resultado</th><th>Detalhes e evidências</th></tr>")
        for i in por[cod]:
            det = "".join(f"<li>{html.escape(x)}</li>" for x in i["detalhes"])
            tec = (f"<details><summary class='mut'>erro técnico</summary><pre class='mut'>{html.escape(i['erro_tecnico'][-1500:])}"
                   f"</pre></details>") if i.get("erro_tecnico") else ""
            partes.append(f"<tr data-st='{html.escape(i['status'])}'><td>{html.escape(i['titulo'])}<div class='mut'>"
                          f"{i['duracao_s']}s</div></td><td>{html.escape(i['papel'])}</td><td>{_st(i['status'])}</td>"
                          f"<td><ul class='det'>{det}</ul>{_prints(i, '.')}{tec}"
                          f"<div class='mut'>{html.escape(i.get('url') or '')}</div></td></tr>")
        partes.append("</table>")
    partes.append("</div></body></html>")
    destino = os.path.join(pasta, "relatorio.html")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("".join(partes))
    return destino


def relatorio_comparativo(pastas, destino):
    """pastas: {'antigo': pasta, 'novo': pasta}"""
    dados = {}
    for amb, p in pastas.items():
        with open(os.path.join(p, "resultados.json"), encoding="utf-8") as f:
            dados[amb] = json.load(f)
    ambs = list(dados)
    chaves = []
    for amb in ambs:
        for i in dados[amb]["itens"]:
            k = (i["codigo"], i["titulo"], i["papel"])
            if k not in chaves:
                chaves.append(k)
    idx = {amb: {(i["codigo"], i["titulo"], i["papel"]): i for i in dados[amb]["itens"]} for amb in ambs}
    base = os.path.dirname(destino)
    partes = [f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
              f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>Comparação Moodle</title>"
              f"<style>{CSS}</style><script>{JS}</script></head><body><div class='wrap'>"
              f"<h1>Comparação entre ambientes: {' × '.join(ambs)}</h1>"
              f"<div class='mut'>Gerado em {time.strftime('%d/%m/%Y %H:%M')}</div>"]
    for amb in ambs:
        partes.append(f"<h3>{html.escape(amb)} — {html.escape(dados[amb]['meta'].get('url', ''))}</h3>"
                      + _cards(_resumo(dados[amb]["itens"])))
    # tempos médios
    tempos = {amb: next((i["dados"].get("media") for i in dados[amb]["itens"] if i["codigo"] == "X06"), None) for amb in ambs}
    partes.append("<p>Tempo médio de carregamento: " + " · ".join(f"<b>{a}</b>: {t if t is not None else '-'}s"
                                                                  for a, t in tempos.items()) + "</p>")
    partes.append("<div class='filtros'>Mostrar: <button onclick=\"filtrar('')\">Tudo</button>"
                  "<button onclick=\"filtrar('dif')\">Somente divergências</button></div>")
    partes.append("<table><tr><th style='width:22%'>Verificação</th>" + "".join(
        f"<th>{html.escape(a)}</th>" for a in ambs) + "</tr>")
    atual = None
    for k in sorted(chaves, key=lambda k: (k[0].startswith("X"), k[0])):
        if k[0] != atual:
            atual = k[0]
            partes.append(f"<tr><th colspan='{len(ambs) + 1}'>{k[0]} — {html.escape(ROTEIRO.get(k[0], ''))}</th></tr>")
        sts = [idx[a].get(k, {}).get("status", "—") for a in ambs]
        dif = "dif" if len(set(sts)) > 1 else "igual"
        linha = f"<tr data-st='{dif}'><td>{html.escape(k[1])}<div class='mut'>{html.escape(k[2])}</div></td>"
        for a in ambs:
            i = idx[a].get(k)
            if not i:
                linha += "<td class='mut'>não executado</td>"
                continue
            rel = os.path.relpath(pastas[a], base)
            det = "".join(f"<li>{html.escape(x)}</li>" for x in i["detalhes"][:12])
            linha += f"<td>{_st(i['status'])}<ul class='det'>{det}</ul>{_prints(i, rel)}</td>"
        partes.append(linha + "</tr>")
    partes.append("</table></div></body></html>")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("".join(partes))
    return destino


# ----------------------------------------------------------------------------- erros.html
# Diagnóstico provável a partir do texto das falhas (padrão -> causa e ação sugerida)
DIAGNOSTICOS = [
    (r"mod_qbank|transfer_question|Banco de questões|sem questões|questões ao questionário",
     "Cron: migração do banco de questões",
     "As tarefas ad hoc de migração do banco de questões (Moodle 5) não foram executadas. "
     "Verificar se o cron (admin/cli/cron.php) está rodando e reprocessar as tarefas ad hoc com falha."),
    (r"Remoção em progresso|Total do curso",
     "Cron: exclusões pendentes e recálculo de notas",
     "Atividades excluídas continuam '[Remoção em progresso]' e os totais do livro de notas não são recalculados. "
     "A exclusão e o recálculo dependem do cron."),
    (r"Notificação ainda não chegou|notificação",
     "Cron: envio de notificações e e-mails",
     "Notificações e e-mails do fórum são enviados pelo cron. Conferir o cron e a fila de mensagens."),
    (r"Mustache_Engine",
     "Plugin incompatível",
     "Um plugin usa a classe antiga 'Mustache_Engine', removida no Moodle 5. Atualizar ou desativar o plugin (formato 'Blocos' / format_tiles)."),
    (r"JavaScript|supabase|onclick",
     "Front-end / tema",
     "Erros de JavaScript no console (widget de suporte externo inacessível e script do tema). Não impedem o uso, mas devem ser corrigidos."),
    (r"Página lenta",
     "Desempenho",
     "Páginas de edição demorando mais que o limite configurado."),
    (r"nova janela|pop-up",
     "Configuração do curso",
     "Recomendação pedagógica: configurar links externos para abrir em nova janela."),
    (r"HTTP 403|robôs",
     "Verificação manual",
     "O site externo bloqueia verificação automática; abrir o link manualmente para confirmar."),
]


def _diagnostico(item):
    texto = item["titulo"] + " " + " ".join(item["detalhes"])
    import re as _re
    for padrao, causa, acao in DIAGNOSTICOS:
        if _re.search(padrao, texto, _re.I):
            return causa, acao
    return "A investigar", "Ver detalhes e prints."


def relatorio_erros(pasta):
    """Gera erros.html: somente FALHAS e AVISOS, agrupados por causa provável, com prints."""
    with open(os.path.join(pasta, "resultados.json"), encoding="utf-8") as f:
        d = json.load(f)
    ruins = [i for i in d["itens"] if i["status"] in (FALHA, AVISO, MANUAL)]
    falhas = [i for i in ruins if i["status"] == FALHA]
    grupos = {}
    for i in ruins:
        causa, acao = _diagnostico(i)
        grupos.setdefault((causa, acao), []).append(i)
    ordem_causa = lambda k: (-sum(x["status"] == FALHA for x in grupos[k]), -len(grupos[k]))

    css_extra = """
    .grupo{background:var(--card);border:1px solid var(--bd);border-left:6px solid var(--cor);border-radius:8px;padding:12px 16px;margin:14px 0}
    .grupo h2{border:0;margin:0 0 4px;font-size:1.25em}
    .acao{margin:4px 0 10px}
    .item{border-top:1px solid var(--bd);padding:10px 0}
    .item h3{margin:0 0 4px;font-size:1.02em}
    .tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--bd);margin-right:6px}
    li.ruim{font-weight:600}
    """
    p = [f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Erros - Moodle {html.escape(d['ambiente'])}</title><style>{CSS}{css_extra}</style></head>"
         f"<body><div class='wrap'><h1>Erros encontrados — ambiente <em>{html.escape(d['ambiente'])}</em></h1>"
         f"<div class='mut'>{html.escape(d['meta'].get('url', ''))} · curso {d['meta'].get('curso_id', '')} · "
         f"estudante: {html.escape(d['meta'].get('modo_aluno', ''))} · execução de {html.escape(d['meta'].get('data', ''))}"
         f" · <a href='relatorio.html'>relatório completo</a></div>",
         _cards({FALHA: len(falhas), AVISO: sum(i['status'] == AVISO for i in ruins),
                 MANUAL: sum(i['status'] == MANUAL for i in ruins),
                 "Verificações no total": len(d["itens"])}),
         "<h2>Resumo por causa provável</h2><table><tr><th>Causa provável</th><th>Falhas</th><th>Avisos</th>"
         "<th>Itens do roteiro afetados</th><th>Ação sugerida</th></tr>"]
    for k in sorted(grupos, key=ordem_causa):
        its = grupos[k]
        cods = sorted({f"{i['codigo']} {ROTEIRO.get(i['codigo'], '')}" for i in its})
        p.append(f"<tr><td><b>{html.escape(k[0])}</b></td><td>{sum(i['status'] == FALHA for i in its)}</td>"
                 f"<td>{sum(i['status'] != FALHA for i in its)}</td><td>{'<br>'.join(html.escape(c) for c in cods)}</td>"
                 f"<td>{html.escape(k[1])}</td></tr>")
    p.append("</table>")
    for k in sorted(grupos, key=ordem_causa):
        its = sorted(grupos[k], key=lambda i: (i["status"] != FALHA, i["codigo"]))
        cor = COR[FALHA] if any(i["status"] == FALHA for i in its) else COR[AVISO]
        p.append(f"<div class='grupo' style='--cor:{cor}'><h2>{html.escape(k[0])}</h2>"
                 f"<div class='acao mut'>{html.escape(k[1])}</div>")
        for i in its:
            det = "".join(
                f"<li class='{'ruim' if x[:1] in '✘⚠👁' else ''}'>{html.escape(x)}</li>"
                for x in i["detalhes"] if not (x.startswith("ℹ") and "JavaScript" in x))
            p.append(f"<div class='item'><h3>{_st(i['status'])} &nbsp;{html.escape(i['titulo'])}</h3>"
                     f"<span class='tag'>{i['codigo']} — {html.escape(ROTEIRO.get(i['codigo'], ''))}</span>"
                     f"<span class='tag'>{html.escape(i['papel'])}</span>"
                     f"<ul class='det'>{det}</ul>{_prints(i, '.')}"
                     f"<div class='mut'>{html.escape(i.get('url') or '')}</div></div>")
        p.append("</div>")
    if not ruins:
        p.append("<p>Nenhuma falha ou aviso nesta execução. 🎉</p>")
    p.append("</div></body></html>")
    destino = os.path.join(pasta, "erros.html")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("".join(p))
    return destino
