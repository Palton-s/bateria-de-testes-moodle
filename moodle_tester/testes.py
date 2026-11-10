"""Testes do roteiro (R01..R11) e extras (X01..X07), executados como um usuário faria."""
import hashlib
import os
import re
import shutil
import time
from urllib.parse import urlparse

import requests

from .core import MoodleError
from .resultado import OK, FALHA, AVISO, MANUAL, NA

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def md5(caminho_ou_bytes):
    h = hashlib.md5()
    if isinstance(caminho_ou_bytes, (bytes, bytearray)):
        h.update(caminho_ou_bytes)
    else:
        with open(caminho_ou_bytes, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


class Suite:
    def __init__(self, reg, prof, aluno, modo_aluno, cid, cm, arq, opcoes, secids):
        """
        prof: navegador logado como professor
        aluno: navegador do estudante (outra conta) ou o mesmo navegador do professor (modo 'papel')
        modo_aluno: 'conta' (conta de estudante real) ou 'papel' (Mudar papel para Estudante)
        """
        self.reg, self.prof, self.aluno, self.modo = reg, prof, aluno, modo_aluno
        self.cid, self.cm, self.arq, self.op, self.secids = cid, cm, arq, opcoes, secids
        self.papel_estudante = opcoes.get("papel_estudante", "Estudante")
        self.links_externos = {}
        self.envio_feito = False
        self.tentativa_quiz = None
        self.nota_tarefa = None
        self.aluno_id, self.aluno_nome = None, None
        if modo_aluno == "conta":
            try:
                aluno.get("user/profile.php")
                import re as _re
                mm = _re.search(r"[?&]id=(\d+)", " ".join(a.get_attribute("href") or "" for a in aluno.acha(
                    "a[href*='user/edit.php?id='], a[href*='user/profile.php?id='], a[href*='message/index.php?id=']")))
                self.aluno_id = mm.group(1) if mm else None
                h = aluno.acha("#region-main h2, .page-header-headings h1, h1")
                self.aluno_nome = h[0].text.strip() if h else None
            except Exception:
                pass
        self.resetar_conclusao = None  # definido pelo executor (Preparador.resetar_conclusao)

    # ------------------------------------------------------------------ papéis
    def como_aluno(self):
        """Garante que o navegador do aluno esteja no papel de estudante."""
        if self.modo == "papel":
            self.prof.mudar_papel(self.cid, self.papel_estudante)
        return self.aluno

    def como_professor(self):
        if self.modo == "papel":
            self.prof.voltar_papel_normal(self.cid)
        return self.prof

    def t(self, codigo, titulo, nav, papel):
        if papel == "Professor" and nav is self.prof:
            try:
                self.como_professor()
            except Exception as e:
                self.reg.log(f"Aviso: não consegui voltar ao papel de professor: {e}")
        return self.reg.teste(codigo, titulo, nav, papel)

    # ================================================================== X01
    def x01_acesso(self):
        for nome, nav in (("Professor", self.prof),) + ((("Estudante", self.aluno),) if self.modo == "conta" else ()):
            with self.t("X01", "Painel e Meus cursos", nav, nome) as t:
                dt = nav.get("my/")
                t.checar(nav.existe("#page-my-index, body.pagelayout-mydashboard, #region-main"),
                         f"Painel carregou ({dt:.1f}s)", "Painel não carregou")
                t.verificar_pagina()
                dt = nav.get("my/courses.php")
                time.sleep(2)
                cursos = nav.js("return [...new Set([...document.querySelectorAll('a[href*=\"course/view.php?id=\"]')]"
                                ".map(a=>a.href))].length")
                t.checar(cursos > 0, f"Meus cursos listou {cursos} curso(s) ({dt:.1f}s)",
                         "Meus cursos não listou nenhum curso")
                t.checar(nav.existe(f"a[href*='course/view.php?id={self.cid}']"),
                         "Curso de teste aparece em Meus cursos", "Curso de teste NÃO aparece em Meus cursos",
                         nivel=AVISO)
                t.verificar_pagina()
                # menu do usuário e páginas comuns
                for pag, nome_pag in (("user/profile.php", "Perfil"), ("calendar/view.php?view=month", "Calendário"),
                                      ("message/index.php", "Mensagens"), ("user/preferences.php", "Preferências"),
                                      ("grade/report/overview/index.php", "Notas (visão geral)")):
                    dt = nav.get(pag)
                    erros = nav.erros_pagina()
                    if erros:
                        t.falha(f"{nome_pag}: {erros[0][:200]}")
                    else:
                        t.ok(f"{nome_pag} abriu ({dt:.1f}s)")

    # ================================================================== R01
    def r01_formato_navegacao(self):
        p = self.prof
        with self.t("R01", "Estrutura, índice do curso e navegação", p, "Professor") as t:
            p.get(f"course/view.php?id={self.cid}")
            fmt = re.search(r"format-(\w+)", p.um("body").get_attribute("class"))
            t.info(f"Formato do curso: {fmt.group(1) if fmt else 'desconhecido'}")
            secs = p.secoes_curso(self.cid)
            t.checar(len(secs) >= 5, f"{len(secs)} seções exibidas", f"Apenas {len(secs)} seções exibidas")
            padrao = [s["nome"] for s in secs if re.fullmatch(r"(Nova seção|Tópico \d+|Topic \d+|New section|Seção \d+)",
                                                                  s["nome"] or "")]
            if padrao:
                t.aviso(f"Seções com nome padrão (não pedagógico): {', '.join(padrao)}", print_=False)
            # índice do curso (gaveta lateral)
            idx = p.js("return document.querySelectorAll('#courseindex .courseindex-section').length")
            t.checar(idx == len(secs), f"Índice do curso lista as {idx} seções",
                     f"Índice do curso lista {idx} seções, página mostra {len(secs)}", nivel=AVISO)
            # recolher/expandir todas as seções
            botao = p.acha("#collapsesections, a[data-action='collapseall'], .collapseexpand")
            if botao:
                p.clicar(botao[0])
                time.sleep(0.8)
                rec = p.js("return document.querySelectorAll('.course-content-item-content.collapse:not(.show)').length")
                p.clicar(botao[0])
                time.sleep(0.8)
                t.checar(rec > 0, f"Recolher/expandir todas as seções funcionou ({rec} recolhidas)",
                         "Botão 'Recolher tudo' não recolheu as seções", nivel=AVISO)
            # navegar por cada seção (página da seção)
            for s in secs[1:]:
                dt = p.get(f"course/section.php?id={s['id']}")
                if "section.php" not in p.d.current_url and "view.php" not in p.d.current_url:
                    t.aviso(f"Página da seção '{s['nome']}' redirecionou para {p.d.current_url}")
                    continue
                if p.erros_pagina():
                    t.falha(f"Erro ao abrir a seção '{s['nome']}': {p.erros_pagina()[0][:150]}")
                else:
                    t.ok(f"Seção '{s['nome']}' abriu ({dt:.1f}s)")
            # abas de navegação do curso
            p.get(f"course/view.php?id={self.cid}")
            abas = p.js("return [...document.querySelectorAll('.secondary-navigation a.nav-link, .secondary-navigation a.dropdown-item')]"
                        ".filter(a=>a.href && !a.href.endsWith('#')).map(a=>[a.textContent.trim(), a.href])")
            for nome, href in abas:
                dt = p.get(href)
                erros = p.erros_pagina()
                if erros:
                    t.falha(f"Aba '{nome}': {erros[0][:150]}")
                else:
                    t.ok(f"Aba '{nome}' abriu ({dt:.1f}s)")
            # navegação anterior/próxima dentro das atividades
            p.get(f"mod/page/view.php?id={self.cm['plano_pagina']}")
            prox = p.acha("#next-activity-link, a#next-activity-link, .activity-navigation a[id*='next']")
            if prox:
                alvo = prox[0].text
                p.clicar(prox[0])
                t.ok(f"Botão 'próxima atividade' levou a: {alvo.strip()[:60]}")
            else:
                t.aviso("Navegação 'Atividade anterior/próxima' não encontrada", print_=False)
            t.foto()

        if self.op.get("testar_todos_formatos", True):
            self._r01_formatos()

        a = self.como_aluno()
        with self.t("R01", "Navegação do curso como estudante", a, "Estudante") as t:
            a.get(f"course/view.php?id={self.cid}")
            secs = a.secoes_curso(self.cid)
            t.checar(len(secs) >= 5, f"Estudante vê {len(secs)} seções", f"Estudante vê só {len(secs)} seções")
            nomes = [x["nome"] for x in secs]
            t.info("Seções: " + " | ".join(nomes))
            ativ = a.atividades_curso(self.cid)
            t.ok(f"{len(ativ)} atividades/recursos visíveis ao estudante")
            t.checar(not a.existe("input[name='setmode']") or self.modo == "papel",
                     "Estudante não tem botão de modo de edição", "Estudante vê o botão de modo de edição")
            t.verificar_pagina()
            t.foto()
        self.como_professor()

    def _r01_formatos(self):
        p = self.prof
        p.get(f"course/edit.php?id={self.cid}")
        original = p.js("return document.getElementById('id_format').value")
        opcoes = p.js("return [...document.getElementById('id_format').options].map(o=>[o.value,o.text])")
        ignorar = set(self.op.get("formatos_ignorar", []))
        testes = [(v, n) for v, n in opcoes if v not in ignorar]
        testes.append((original, "layout: uma seção por página"))
        for valor, nome in testes:
            uma_por_pagina = nome.startswith("layout")
            with self.t("R01", f"Formato do curso: {nome}", p, "Professor") as t:
                p.get(f"course/edit.php?id={self.cid}")
                p.expandir_formulario()
                if p.js("return document.getElementById('id_format').value") != valor:
                    p.selecionar("#id_format", valor)
                    p.aguardar_carregar(1.5)  # o Moodle recarrega o formulário ao trocar o formato
                    p.expandir_formulario()
                if p.existe("#id_coursedisplay"):
                    p.selecionar("#id_coursedisplay", 1 if uma_por_pagina else 0)
                p.clicar("#id_saveanddisplay" if p.existe("#id_saveanddisplay") else "#id_submitbutton")
                if "course/edit.php" in p.d.current_url:
                    erros = [e.text for e in p.acha(".invalid-feedback, .error") if e.is_displayed() and e.text.strip()]
                    # preenche selects inválidos com a primeira opção válida e tenta de novo
                    ajustados = p.js("""
                        const out=[];
                        document.querySelectorAll('form.mform select').forEach(s=>{
                          const grp = s.closest('.fitem, .form-group');
                          const inval = s.classList.contains('is-invalid') || (grp && [...grp.querySelectorAll('.invalid-feedback')].some(f=>f.textContent.trim()));
                          if(!inval) return;
                          const o=[...s.options].find(o=>o.value && o.value!=='0' && o.value!==s.value) || [...s.options].find(o=>o.value);
                          if(o){ s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true})); out.push((s.name||s.id)+'='+o.text); }
                        }); return out;""") or []
                    if ajustados:
                        p.clicar("#id_saveanddisplay" if p.existe("#id_saveanddisplay") else "#id_submitbutton")
                    if "course/edit.php" in p.d.current_url:
                        t.aviso("O formato exige configuração adicional e não foi salvo automaticamente: "
                                + " | ".join(erros) + (f" (tentativa: {', '.join(ajustados)})" if ajustados else ""))
                        continue
                    t.info("Formato exigiu configuração adicional, preenchida automaticamente: " + ", ".join(ajustados))
                p.get(f"course/view.php?id={self.cid}")
                body = p.um("body").get_attribute("class")
                t.checar(f"format-{valor}" in body, f"Curso exibido no formato '{valor}'",
                         f"Página não está no formato '{valor}' (classes: {body[:80]})", nivel=AVISO)
                texto = p.texto_pagina()
                visiveis = [n for n in ("Apresentação", "Aula 1", "Aula 2", "Avaliação") if n in texto]
                t.checar(len(visiveis) >= 3 or uma_por_pagina,
                         f"Seções visíveis: {', '.join(visiveis)}",
                         f"Poucas seções visíveis no formato '{valor}': {visiveis}", nivel=AVISO)
                if uma_por_pagina:
                    links = p.acha("a[href*='section.php'], a[href*='section=']")
                    t.checar(links, f"Layout uma seção por página exibe {len(links)} links para seções",
                             "Layout uma seção por página sem links para as seções", nivel=AVISO)
                t.verificar_pagina()
                t.foto()
        with self.t("R01", "Restaurar formato original do curso", p, "Professor") as t:
            p.get(f"course/edit.php?id={self.cid}")
            p.expandir_formulario()
            if p.js("return document.getElementById('id_format').value") != original:
                p.selecionar("#id_format", original)
                p.aguardar_carregar(1.5)
                p.expandir_formulario()
            if p.existe("#id_coursedisplay"):
                p.selecionar("#id_coursedisplay", 0)
            p.clicar("#id_saveanddisplay" if p.existe("#id_saveanddisplay") else "#id_submitbutton")
            t.checar(f"format-{original}" in p.um("body").get_attribute("class"),
                     f"Formato restaurado para '{original}'", f"Formato não voltou para '{original}'")

    # ================================================================== R02
    def r02_plano_ensino(self):
        a = self.como_aluno()
        with self.t("R02", "Conteúdo do Plano de Ensino (página)", a, "Estudante") as t:
            dt = a.get(f"mod/page/view.php?id={self.cm['plano_pagina']}")
            t.ok(f"Página do Plano de Ensino abriu ({dt:.1f}s)")
            txt = a.texto_pagina()
            t.checar(a.existe("#region-main table"), "Cronograma (tabela) presente", "Cronograma (tabela) não encontrado")
            t.checar(re.search(r"Crit[ée]rios de avalia", txt, re.I), "Critérios de avaliação presentes",
                     "Critérios de avaliação não encontrados")
            pontos = [float(x.replace(",", ".")) for x in re.findall(r"(\d+,\d+) pontos", txt)]
            if pontos:
                total_decl = max(pontos)
                soma = sum(pontos) - total_decl
                t.checar(abs(soma - total_decl) < 0.01, f"Soma dos critérios ({soma}) confere com o total ({total_decl})",
                         f"Soma dos critérios ({soma}) diferente do total informado ({total_decl})")
            links = a.js("return [...document.querySelectorAll('#region-main a[href^=\"http\"]')].map(a=>[a.textContent.trim(),a.href])")
            t.info(f"{len(links)} link(s) no plano de ensino")
            for nome, href in links:
                self.links_externos[href] = f"Plano de Ensino: {nome}"
            t.verificar_pagina()
            t.foto()

        with self.t("R02", "Plano de Ensino (arquivo PDF) - visualização", a, "Estudante") as t:
            info = self._baixar_recurso(a, self.cm["plano_pdf"], t)
            if info:
                t.dados["md5_antes"] = info["md5"]
        self.como_professor()

        p = self.prof
        with self.t("R02", "Atualizar arquivo do Plano de Ensino (substituir pelo v2)", p, "Professor") as t:
            if not self.op.get("permitir_alteracoes", True):
                t.na("Alterações desativadas na configuração")
            else:
                pasta = os.path.dirname(self.arq["plano_v2"])
                tmp = os.path.join(pasta, "substituicao")
                os.makedirs(tmp, exist_ok=True)
                mesmo_nome = os.path.join(tmp, os.path.basename(self.arq["plano_v1"]))
                shutil.copy(self.arq["plano_v2"], mesmo_nome)  # mesmo nome -> o Moodle pede para sobrescrever
                p.get(f"course/modedit.php?update={self.cm['plano_pdf']}&return=1")
                p.upload_filemanager(mesmo_nome)
                t.ok("Novo arquivo enviado pelo seletor de arquivos (sobrescrevendo o anterior)")
                p.salvar_form()
                t.verificar_pagina()
        a = self.como_aluno()
        with self.t("R02", "Plano de Ensino - estudante recebe o arquivo atualizado", a, "Estudante") as t:
            info = self._baixar_recurso(a, self.cm["plano_pdf"], t)
            if info:
                t.checar(info["md5"] == md5(self.arq["plano_v2"]), "Estudante baixa a versão NOVA (v2) do arquivo",
                         "Estudante ainda recebe a versão antiga do arquivo (cache ou falha na substituição)")
        self.como_professor()

    # ------------------------------------------------------------------ util arquivos
    def _baixar_recurso(self, nav, cmid, t, esperado=None):
        """Abre o recurso como usuário, descobre o arquivo e valida o download (status, tipo, tamanho)."""
        dt = nav.get(f"mod/resource/view.php?id={cmid}")
        janela0 = nav.d.current_window_handle
        url = nav.d.current_url
        arquivo = None
        if "pluginfile.php" in url:
            arquivo = url
            t.ok(f"Arquivo aberto diretamente no navegador ({dt:.1f}s)")
        else:
            emb = nav.acha("#resourceobject, object[data*='pluginfile'], iframe[src*='pluginfile'], embed[src*='pluginfile']")
            if emb:
                arquivo = emb[0].get_attribute("data") or emb[0].get_attribute("src")
                t.ok(f"Arquivo incorporado na página do Moodle ({dt:.1f}s)")
            links = nav.acha("#region-main a[href*='pluginfile.php'], .resourceworkaround a")
            if not arquivo and links:
                arquivo = links[0].get_attribute("href")
                onclick = links[0].get_attribute("onclick") or ""
                nav.clicar(links[0])
                time.sleep(2)
                novas = [h for h in nav.d.window_handles if h != janela0]
                if novas:
                    nav.d.switch_to.window(novas[-1])
                    t.ok(f"Link abriu em nova janela/pop-up: {nav.d.current_url[:90]}")
                    nav.d.close()
                    nav.d.switch_to.window(janela0)
                elif "window.open" in onclick:
                    t.aviso("Link configurado como pop-up, mas nenhuma janela nova abriu (bloqueador?)", print_=False)
                else:
                    t.ok("Link de download clicado")
        s = nav.cookies_requests()
        if not arquivo:
            # "Forçar download": o view.php redireciona direto para o arquivo
            r0 = s.get(nav.url(f"mod/resource/view.php?id={cmid}"), allow_redirects=False, timeout=30)
            loc = r0.headers.get("Location", "")
            if "pluginfile.php" in loc:
                arquivo = loc
                t.ok("Recurso redireciona direto para o download do arquivo")
        if not arquivo:
            t.falha("Não encontrei o arquivo na página do recurso")
            return None
        r = s.get(arquivo, timeout=60)
        tipo = r.headers.get("Content-Type", "")
        disp = r.headers.get("Content-Disposition", "")
        ok = r.status_code == 200 and len(r.content) > 0
        t.checar(ok, f"Download OK: HTTP {r.status_code}, {len(r.content) / 1024:.0f} KB, tipo {tipo.split(';')[0]}",
                 f"Download falhou: HTTP {r.status_code}, {len(r.content)} bytes")
        if "html" in tipo and b"login" in r.content[:5000].lower():
            t.falha("O link do arquivo devolveu a página de login (sessão/permissão)")
        info = {"url": arquivo, "status": r.status_code, "tipo": tipo, "tamanho": len(r.content),
                "md5": md5(r.content), "disposition": disp}
        if esperado:
            if info["md5"] == md5(esperado):
                t.ok("Conteúdo idêntico ao arquivo enviado pelo professor (íntegro)")
            else:
                t.info("Conteúdo difere do arquivo local de referência (o arquivo no curso pode ter sido "
                       "enviado por uma execução anterior)")
        return info

    # ================================================================== R03
    def r03_arquivos(self):
        a = self.como_aluno()
        for chave, nome, local, exibicao in (
                ("pdf_texto", "PDF incorporado", self.arq["texto_base"], "incorporar"),
                ("pdf_leitura", "PDF em pop-up", self.arq["leitura"], "pop-up"),
                ("pptx", "Slides PPTX (forçar download)", self.arq["slides"], "download")):
            with self.t("R03", f"Abrir {nome}", a, "Estudante") as t:
                info = self._baixar_recurso(a, self.cm[chave], t, esperado=local)
                if not info:
                    continue
                if local.endswith(".pdf"):
                    t.checar("pdf" in info["tipo"], "Servidor envia o PDF com tipo application/pdf (abre no navegador)",
                             f"Tipo inesperado para PDF: {info['tipo']}", nivel=AVISO)
                    # abre o PDF no visualizador do Chrome
                    a.d.get(info["url"])
                    time.sleep(2)
                    t.checar(a.d.execute_script("return document.contentType") == "application/pdf"
                             or a.existe("embed[type='application/pdf'], pdf-viewer"),
                             "PDF visualizado no navegador", "PDF não abriu no visualizador do navegador", nivel=AVISO)
                    t.foto()
                else:
                    t.checar("attachment" in info["disposition"].lower() or "presentation" in info["tipo"],
                             "PPTX é entregue como download", f"PPTX entregue como {info['tipo']} / {info['disposition']}",
                             nivel=AVISO)
                    # download real pelo navegador
                    antes = set(os.listdir(a.downloads_dir))
                    a.d.get(info["url"])
                    for _ in range(20):
                        time.sleep(0.5)
                        novos = [f for f in set(os.listdir(a.downloads_dir)) - antes if not f.endswith(".crdownload")]
                        if novos:
                            break
                    novos = [f for f in set(os.listdir(a.downloads_dir)) - antes if not f.endswith(".crdownload")]
                    t.checar(novos, f"Navegador baixou o arquivo: {novos[0] if novos else ''}",
                             "Navegador não concluiu o download", nivel=AVISO)
                a.get(f"course/view.php?id={self.cid}")
                t.verificar_pagina()
        self.como_professor()

    # ================================================================== R04
    def r04_links(self):
        a = self.como_aluno()
        for chave in ("url_site", "url_video"):
            with self.t("R04", f"Recurso URL: {chave}", a, "Estudante") as t:
                janela0 = a.d.current_window_handle
                a.get(f"course/view.php?id={self.cid}")
                link = a.acha(f"#module-{self.cm[chave]} a.aalink, #module-{self.cm[chave]} .activityname a")
                if not link:
                    t.falha("Link do recurso não encontrado na página do curso")
                    continue
                nome = link[0].text.strip()
                a.clicar(link[0])
                time.sleep(2.5)
                novas = [h for h in a.d.window_handles if h != janela0]
                if novas:
                    a.d.switch_to.window(novas[-1])
                    destino = a.d.current_url
                    t.ok(f"'{nome}' abriu em NOVA janela: {destino[:100]} (título: {a.d.title[:60]})")
                    t.foto()
                    a.d.close()
                    a.d.switch_to.window(janela0)
                else:
                    destino = a.d.current_url
                    if "mod/url/view.php" in destino:
                        ext = a.acha(".urlworkaround a, #region-main a[href^='http']:not([href*='" + urlparse(a.base).netloc + "'])")
                        if ext:
                            destino = ext[0].get_attribute("href")
                            t.info(f"Moodle exibiu página intermediária com o link: {destino[:100]}")
                    t.ok(f"'{nome}' abriu na mesma janela: {destino[:100]}")
                    t.aviso("Recomendado abrir links externos em nova janela (configurar 'Exibir: Em uma janela pop-up')",
                            print_=False) if "youtube" in destino or "unb.br" in destino else None
                    t.foto()
                self.links_externos.setdefault(destino if destino.startswith("http") else "", f"Recurso URL {nome}")
        # todos os links externos do curso (rótulos, páginas, URLs)
        with self.t("R04", "Verificação de todos os links externos do curso", a, "Estudante") as t:
            host = urlparse(a.base).netloc
            paginas = [f"course/view.php?id={self.cid}"] + [f"mod/page/view.php?id={self.cm[k]}"
                                                            for k in ("plano_pagina", "pagina_aula1") if k in self.cm]
            for pg in paginas:
                a.get(pg)
                for nome, href in a.js("return [...document.querySelectorAll('#region-main a[href^=\"http\"], #region-main iframe[src^=\"http\"]')]"
                                       ".map(e=>[(e.textContent||e.title||'').trim().slice(0,60), e.href||e.src])"):
                    if host not in href and href:
                        self.links_externos.setdefault(href, f"{nome} ({pg})")
            self.links_externos.pop("", None)
            lim = int(self.op.get("max_links_externos", 40))
            quebrados = 0
            for href, origem in list(self.links_externos.items())[:lim]:
                st, det = self._checar_link(href)
                if st == OK:
                    t.ok(f"{det} → {href[:90]}")
                elif st == AVISO:
                    t.aviso(f"{det} → {href[:90]} (origem: {origem})", print_=False)
                else:
                    quebrados += 1
                    t.falha(f"{det} → {href[:90]} (origem: {origem})", print_=False)
            t.dados["links"] = self.links_externos
            if quebrados:
                t.foto()
        with self.t("R04", "Vídeo do YouTube incorporado na página", a, "Estudante") as t:
            a.get(f"mod/page/view.php?id={self.cm['pagina_aula1']}")
            ifr = a.acha("#region-main iframe[src*='youtube']")
            if not ifr:
                t.falha("Iframe do YouTube não encontrado (pode ter sido removido pelo filtro de HTML)")
            else:
                src = ifr[0].get_attribute("src")
                t.ok(f"Iframe presente: {src[:80]}")
                a.d.switch_to.frame(ifr[0])
                time.sleep(3)
                erro = a.js("return document.body ? document.body.innerText.slice(0,300) : ''")
                a.d.switch_to.default_content()
                t.checar(not re.search(r"indisponível|unavailable|Error \d+|recusou", erro or "", re.I),
                         "Player do YouTube carregou", f"Player com erro: {erro[:120]}")
                t.foto()
            a.get(f"mod/url/view.php?id={self.cm['url_video']}")
        self.como_professor()

    def _checar_link(self, href):
        try:
            if "youtube.com/watch" in href or "youtu.be/" in href or "youtube.com/embed/" in href:
                vid = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", href)
                r = requests.get("https://www.youtube.com/oembed", params={
                    "url": f"https://www.youtube.com/watch?v={vid.group(1)}", "format": "json"}, timeout=15)
                if r.status_code == 200:
                    return OK, f"Vídeo disponível: \"{r.json().get('title', '')[:50]}\""
                return FALHA, f"Vídeo indisponível/privado (oEmbed HTTP {r.status_code})"
            r = requests.head(href, allow_redirects=True, timeout=15, headers={"User-Agent": UA})
            if r.status_code in (403, 405, 400) or r.status_code >= 500:
                r = requests.get(href, allow_redirects=True, timeout=20, headers={"User-Agent": UA}, stream=True)
            if r.status_code < 400:
                return OK, f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 429):
                return AVISO, f"HTTP {r.status_code} (bloqueio do site a robôs - conferir manualmente)"
            return FALHA, f"Link quebrado HTTP {r.status_code}"
        except requests.RequestException as e:
            return FALHA, f"Link inacessível ({type(e).__name__})"

    # ================================================================== R05
    def r05_rotulos(self):
        for papel in ("Professor", "Estudante"):
            nav = self.como_aluno() if papel == "Estudante" else self.como_professor()
            with self.t("R05", "Rótulos, cabeçalhos e organização visual", nav, papel) as t:
                nav.get(f"course/view.php?id={self.cid}")
                rotulos = nav.js("""return [...document.querySelectorAll('li.activity.modtype_label')].map(l => ({
                    id: l.id, texto: l.innerText.trim().slice(0,80),
                    cabecalhos: [...l.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h=>[+h.tagName[1], h.textContent.trim()]),
                    alertas: l.querySelectorAll('.alert').length,
                    imgs_sem_alt: [...l.querySelectorAll('img')].filter(i=>!i.alt).length,
                    vazio: l.innerText.trim().length === 0}))""")
                t.checar(rotulos, f"{len(rotulos)} rótulo(s) visíveis", "Nenhum rótulo visível no curso")
                for r in rotulos:
                    niveis = [c[0] for c in r["cabecalhos"]]
                    pulos = [f"h{niveis[i - 1]}→h{niveis[i]}" for i in range(1, len(niveis)) if niveis[i] - niveis[i - 1] > 1]
                    if r["vazio"]:
                        t.aviso(f"Rótulo vazio ({r['id']})", print_=False)
                    elif pulos:
                        t.aviso(f"Hierarquia de cabeçalhos com saltos ({', '.join(pulos)}) em '{r['texto'][:40]}'", print_=False)
                    else:
                        t.ok(f"Rótulo '{r['texto'][:40]}…' com cabeçalhos {['h%d' % n for n in niveis]}"
                             + (f" e {r['alertas']} aviso(s) visual(is)" if r["alertas"] else ""))
                    if r["imgs_sem_alt"]:
                        t.aviso(f"{r['imgs_sem_alt']} imagem(ns) sem texto alternativo em '{r['texto'][:40]}'", print_=False)
                # o aviso visual deve estar realmente visível e com contraste
                alerta = nav.acha("li.modtype_label .alert")
                if alerta:
                    cor = nav.js("const s=getComputedStyle(arguments[0]);return [s.backgroundColor, s.display]", alerta[0])
                    t.checar(cor[1] != "none", f"Aviso visual exibido com destaque (fundo {cor[0]})",
                             "Aviso visual não está sendo exibido")
                vazias = [s["nome"] for s in nav.secoes_curso(self.cid)[1:] if s["atividades"] == 0]
                if vazias and papel == "Professor":
                    t.aviso(f"Seções sem nenhum conteúdo: {', '.join(vazias)}", print_=False)
                t.verificar_pagina()
                t.foto()
        self.como_professor()

    # ================================================================== R06 / X07
    def r06_tarefa(self):
        a = self.como_aluno()
        cm = self.cm["tarefa"]
        with self.t("R06", "Tarefa - instruções, prazo e limite de arquivo visíveis", a, "Estudante") as t:
            self._liberar_aula2(a)
            dt = a.get(f"mod/assign/view.php?id={cm}")
            txt = a.texto_pagina()
            if re.search(r"não disponível|Not available|restri", txt, re.I) and not a.existe(".submissionstatustable, .submissionsummarytable"):
                t.falha("Tarefa bloqueada para o estudante mesmo após concluir a Aula 1")
            t.checar("Instrução" in txt, "Instrução da tarefa visível", "Instrução da tarefa não aparece")
            prazo = self.reg.meta.get("prazo_tarefa", "")
            dia = prazo.split(" ")[0] if prazo else ""
            vence = re.search(r"(Vencimento|Data de entrega|Due)[:\s]*([^\n]+)", txt)
            if vence:
                t.ok(f"Data limite exibida: {vence.group(2).strip()[:60]}")
                d, mth, y = dia.split("/") if dia else ("", "", "")
                if d and d.lstrip("0") not in vence.group(2):
                    t.aviso(f"Data exibida ({vence.group(2)[:40]}) não parece bater com o prazo configurado ({prazo})")
            else:
                t.falha("Data limite de entrega não aparece para o estudante")
            t.checar(re.search(r"Tempo restante|Time remaining", txt), "Tempo restante exibido",
                     "Tempo restante não exibido", nivel=AVISO)
            t.foto()
            # abre o formulário de envio
            botao = [b for b in a.acha("#region-main button, #region-main a.btn, #region-main input[type=submit]")
                     if re.search(r"Adicionar envio|Add submission|Editar envio|Edit submission",
                                  b.text or b.get_attribute("value") or "")]
            if not botao:
                if re.search(r"Enviado para avaliação|Submitted for grading", txt):
                    t.info("Já existe um envio desta conta (execução anterior)")
                    self.envio_feito = True
                    return
                t.falha("Botão 'Adicionar envio' não encontrado")
                return
            a.clicar(botao[0])
            txt = a.texto_pagina()
            lim = re.search(r"Tamanho máximo[^\n]*?([\d.,]+\s*[KMG]B)", txt, re.I)
            t.checar(lim, f"Limite de tamanho exibido no envio: {lim.group(1) if lim else ''}",
                     "Limite de tamanho de arquivo não aparece no formulário de envio")
            if lim and "1" not in lim.group(1):
                t.aviso(f"Limite exibido ({lim.group(1)}) diferente do configurado (1 MB)")
            tipos = re.search(r"Tipos de arquivo aceitos[^\n]*\n?([^\n]+)", txt)
            if tipos:
                t.ok(f"Tipos aceitos exibidos: {tipos.group(1)[:80]}")
            t.foto()

        with self.t("X07", "Bloqueio de arquivo acima do limite (1,6 MB > 1 MB)", a, "Estudante") as t:
            if not a.existe(".filemanager, .fp-btn-add"):
                t.na("Formulário de envio não disponível")
            else:
                self._tentar_upload_invalido(a, self.arq["grande"], t, r"tamanho|size|grande|large|exced", "tamanho")
        with self.t("X07", "Bloqueio de tipo de arquivo não permitido (.txt)", a, "Estudante") as t:
            if not a.existe(".filemanager, .fp-btn-add"):
                t.na("Formulário de envio não disponível")
            else:
                self._tentar_upload_invalido(a, self.arq["proibido"], t, r"tipo|type|não é permitido|not allowed|aceit",
                                             "tipo")

        with self.t("R06", "Tarefa - envio de teste (arquivo + texto online)", a, "Estudante") as t:
            if not self.op.get("permitir_alteracoes", True):
                t.na("Alterações desativadas")
                return
            if self.envio_feito:
                t.na("Envio já realizado em execução anterior")
                return
            if "editsubmission" not in a.d.current_url:
                a.get(f"mod/assign/view.php?id={cm}&action=editsubmission")
            a.editor("id_onlinetext_editor", "<p>Resposta de teste enviada pelo teste automatizado.</p>")
            a.upload_filemanager(self.arq["envio_aluno"])
            t.ok("Arquivo anexado e texto online preenchido")
            a.clicar("#id_submitbutton")
            t.verificar_pagina()
            enviar = [b for b in a.acha("#region-main button, #region-main input[type=submit]")
                      if re.search(r"Enviar tarefa|Submit assignment", b.text or b.get_attribute("value") or "")]
            if enviar:
                a.clicar(enviar[0])
                if a.existe("#id_submissionstatement"):
                    a.marcar("#id_submissionstatement", True)
                cont = a.acha("#id_submitbutton")
                if cont:
                    a.clicar(cont[0])
                t.ok("Clicou em 'Enviar tarefa' e confirmou")
            a.get(f"mod/assign/view.php?id={cm}")
            txt = a.texto_pagina()
            ok = re.search(r"Enviado para avaliação|Submitted for grading", txt)
            t.checar(ok, "Status do envio: 'Enviado para avaliação'",
                     "Status do envio não mudou para 'Enviado para avaliação'")
            if self.modo == "papel" and not ok and re.search(r"Rascunho|Draft|Nenhuma tentativa|No attempt", txt):
                t.info("Observação: no modo 'Mudar papel' o Moodle pode não aceitar envio real; use uma conta de aluno")
            self.envio_feito = bool(ok)
            t.foto()
        self.como_professor()

    def _tentar_upload_invalido(self, a, caminho, t, padrao_erro, oque):
        try:
            a.upload_filemanager(caminho)
            # se chegou aqui, o seletor fechou: o arquivo foi aceito
            t.falha(f"Arquivo inválido ({oque}) foi ACEITO pelo seletor de arquivos")
            # remove o arquivo para não atrapalhar o envio válido
            a.get(a.d.current_url)
        except Exception:
            time.sleep(1)
            textos = a.js("return [...document.querySelectorAll('.moodle-dialogue-base:not(.moodle-dialogue-hidden), "
                          ".modal.show')].map(d => d.innerText).join(String.fromCharCode(10))") or ""
            frases = [l.strip() for l in textos.split("\n") if re.search(padrao_erro, l, re.I) and len(l.strip()) > 8]
            if frases:
                t.ok(f"Moodle bloqueou o arquivo com a mensagem: \"{frases[0][:180]}\"")
            else:
                t.aviso("O arquivo não foi anexado, mas não encontrei uma mensagem de erro clara para o usuário")
            t.foto()
            # fecha os diálogos
            a.js("document.querySelectorAll('.moodle-dialogue-base:not(.moodle-dialogue-hidden) .closebutton, "
                 ".fp-msg-butok, .moodle-dialogue-base button.btn-primary').forEach(b=>{try{b.click()}catch(e){}})")
            time.sleep(0.5)
            a.js("document.querySelectorAll('.moodle-dialogue-base:not(.moodle-dialogue-hidden) .closebutton').forEach(b=>{try{b.click()}catch(e){}})")

    # ================================================================== R07
    def r07_quiz(self):
        p = self.prof
        cm = self.cm["quiz"]
        nq = 0
        with self.t("R07", "Questionário - configuração (tempo, tentativas, questões)", p, "Professor") as t:
            p.get(f"mod/quiz/view.php?id={cm}")
            txt = p.texto_pagina()
            lim = re.search(r"(?:Limite de tempo|Duração máxima|Tempo limite)[:\s]*([^\n]+)", txt)
            tent = re.search(r"Tentativas permitidas[:\s]*([^\n]+)", txt)
            t.checar(lim and "10" in lim.group(1), f"Tempo limite exibido: {lim.group(1) if lim else ''}",
                     f"Tempo limite incorreto/ausente: {lim.group(1) if lim else 'não exibido'}")
            t.checar(tent and "2" in tent.group(1), f"Tentativas permitidas: {tent.group(1) if tent else ''}",
                     f"Tentativas permitidas incorretas/ausentes: {tent.group(1) if tent else 'não exibido'}")
            p.get(f"mod/quiz/edit.php?cmid={cm}")
            nq = p.js("return document.querySelectorAll('li.slot').length")
            qtxt = p.js("return [...document.querySelectorAll('li.slot .questiontext, li.slot .questionname, li.slot .questiontype')].map(e=>e.innerText.trim()).join(' | ')")
            t.checar(nq >= 1, f"{nq} questão(ões) no questionário: {qtxt[:150]}",
                     "Questionário SEM questões: não é possível realizar tentativa. " + self._aviso_qbank(p))
            mx = p.js("var e=document.getElementById('inputmaxgrade');return e?e.value:null")
            t.info(f"Nota máxima do questionário: {mx}")
            if p.existe("a[href*='question/edit.php'], a[href*='qbank']"):
                p.get(f"question/edit.php?cmid={cm}")
                tem_botao = bool([b for b in p.acha("button, input[type=submit], a.btn")
                                  if re.search(r"Criar uma nova questão|Create a new question", b.text or b.get_attribute("value") or "")])
                t.checar(tem_botao, "Banco de questões disponível (botão 'Criar uma nova questão')",
                         "Banco de questões do questionário está vazio/sem o botão 'Criar uma nova questão'. "
                         + self._aviso_qbank(p))
            t.verificar_pagina()
        a = self.como_aluno()
        with self.t("R07", "Questionário - tentativa completa como estudante", a, "Estudante") as t:
            a.get(f"mod/quiz/view.php?id={cm}")
            txt = a.texto_pagina()
            for rotulo in (r"Limite de tempo|Duração máxima|Tempo limite", r"Tentativas permitidas"):
                mm = re.search(rf"({rotulo})[:\s]*([^\n]+)", txt)
                t.checar(mm, f"Estudante vê '{mm.group(1)}: {mm.group(2)}'" if mm else "",
                         f"Estudante não vê '{rotulo.split('|')[0]}'", nivel=AVISO)
            if nq == 0:
                t.falha("Tentativa impossível: questionário sem questões (falha ao criar questões neste ambiente)")
                return self.como_professor()
            botao = a.acha("form[action*='startattempt.php'] button[type=submit], form[action*='startattempt.php'] input[type=submit]")
            if not botao:
                t.falha("Botão para iniciar tentativa não encontrado. Texto: " + txt[:200].replace("\n", " "))
                return self.como_professor()
            a.clicar(botao[0])
            time.sleep(1)
            # modal "Iniciar tentativa" (tempo limitado)
            conf = [b for b in a.acha(".modal.show button, .modal.show input[type=submit], #id_submitbutton") if b.is_displayed()
                    and re.search(r"Iniciar|Start", b.text or b.get_attribute("value") or "")]
            if conf:
                a.clicar(conf[0])
            a.espera(".que", t=30)
            t.checar(a.existe("#quiz-timer, #quiz-time-left, .quiz-timer"), "Cronômetro do tempo limite exibido",
                     "Cronômetro do tempo limite não exibido", nivel=AVISO)
            # responde (as questões podem estar em uma ou várias páginas)
            respondidas = 0
            for _ in range(10):
                for q in a.acha(".que"):
                    cls = q.get_attribute("class")
                    if "truefalse" in cls:
                        op = q.find_elements("css selector", "input[type=radio][value='1']")
                        if op:
                            a.clicar(op[0]); respondidas += 1
                    elif "multichoice" in cls:
                        for lab in q.find_elements("css selector", ".answer div[data-region='answer-label'], .answer label, .answer .flex-fill"):
                            if lab.text.strip().endswith("5") or lab.text.strip() == "5":
                                a.clicar(lab); respondidas += 1
                                break
                    elif "shortanswer" in cls:
                        inp = q.find_elements("css selector", "input[type=text]")
                        if inp:
                            inp[0].clear(); inp[0].send_keys("azul"); respondidas += 1
                prox = a.acha("#mod_quiz-next-nav, input[name=next]")
                if not prox:
                    break
                a.clicar(prox[0])
                if a.existe("#region-main .quizsummaryofattempt, .quizattemptsummary"):
                    break
            t.ok(f"{respondidas} questão(ões) respondida(s)")
            # página de resumo -> enviar tudo
            if not a.existe(".quizsummaryofattempt, .quizattemptsummary"):
                fim = a.acha("a.endtestlink, .endtestlink")
                if fim:
                    a.clicar(fim[0])
            env = [b for b in a.acha("#region-main button, #region-main input[type=submit]")
                   if re.search(r"Enviar tudo e terminar|Submit all and finish", b.text or b.get_attribute("value") or "")]
            if not env:
                t.falha("Botão 'Enviar tudo e terminar' não encontrado")
                return self.como_professor()
            a.clicar(env[0])
            time.sleep(1)
            conf = [b for b in a.acha(".modal.show button, .moodle-dialogue-base input[type=button]") if b.is_displayed()
                    and re.search(r"Enviar tudo|Submit all", b.text or b.get_attribute("value") or "")]
            if conf:
                a.clicar(conf[0])
            a.aguardar_carregar(1)
            txt = a.texto_pagina()
            nota = re.search(r"Avaliar\s*([\d,]+)\s*de\s*([\d,]+)|Nota\s*([\d,]+)\s*de\s*([\d,]+)", txt)
            if "review.php" in a.d.current_url or nota:
                t.ok("Tentativa finalizada e página de revisão exibida")
                if nota:
                    g = [x for x in nota.groups() if x]
                    obtida, maxima = float(g[0].replace(",", ".")), float(g[1].replace(",", "."))
                    t.checar(abs(obtida - maxima) < 0.01, f"Correção automática: {g[0]} de {g[1]} (todas corretas)",
                             f"Correção automática deu {g[0]} de {g[1]}, esperado nota máxima (todas as respostas estavam corretas)")
                    self.tentativa_quiz = obtida
                corretas = len(a.acha(".que.correct, .que .correct"))
                t.info(f"Questões marcadas como corretas na revisão: {corretas}")
            else:
                t.falha("Não chegou à página de revisão após enviar a tentativa")
            t.foto()
        self.como_professor()

    def _aviso_qbank(self, nav):
        mm = re.search(r"As tarefas ad hoc.*?concluídas[^.]*\.", nav.texto_pagina(), re.S)
        return ("Aviso do Moodle: " + mm.group(0).replace("\n", " ")) if mm else ""

    # ================================================================== R08 / R09
    def _tabela_notas(self, p):
        p.get(f"grade/edit/tree/index.php?id={self.cid}")
        return p.js("""
            const rows=[]; document.querySelectorAll('table#grade_edit_tree_table tbody tr, table.setup-grades tbody tr').forEach(r=>{
              const cls=r.className; const nome=(r.querySelector('.column-name, td.name, th.column-name')||r).innerText.replace(/\\s+/g,' ').trim();
              const max=(r.querySelector('.column-range, td.range')||{}).innerText;
              const peso=(r.querySelector('.column-weight input, td.weight input')||{}).value;
              rows.push({cls:cls, nome:nome, max:(max||'').trim(), peso:peso||null});
            }); return rows;""")

    def r08_livro_notas(self):
        p = self.como_professor()
        with self.t("R08", "Configuração do Livro de Notas", p, "Professor") as t:
            linhas = self._tabela_notas(p)
            t.dados["tabela"] = linhas
            txt = p.texto_pagina()
            for nome in ("Tarefa", "Questionário"):
                t.checar(nome in txt, f"Atividade avaliativa '{nome}' listada no livro de notas",
                         f"Atividade avaliativa '{nome}' NÃO aparece no livro de notas")
            total = re.search(r"Total do curso\s*([\d.,]+)", txt.replace("\n", " "))
            esp = self.op.get("nota_total_esperada", [10, 100])
            if total:
                v = float(total.group(1).replace(".", "").replace(",", ".")) if "," in total.group(1) else float(total.group(1))
                t.checar(v in esp, f"Nota máxima do Total do curso = {total.group(1)}",
                         f"Total do curso = {total.group(1)}; esperado {' ou '.join(map(str, esp))}")
                t.dados["total"] = v
            else:
                t.aviso("Não consegui ler a nota máxima do 'Total do curso'")
            maxs = []
            for l in linhas:
                if ("item" in l["cls"] and "category" not in l["cls"]) and re.search(r"[\d,]+", l["max"] or ""):
                    maxs.append((l["nome"][:50], float(re.findall(r"[\d.,]+", l["max"])[-1].replace(",", "."))))
            if maxs:
                t.info("Notas máximas por item: " + "; ".join(f"{n}: {v}" for n, v in maxs))
            # relatório de notas do professor abre
            dt = p.get(f"grade/report/grader/index.php?id={self.cid}")
            t.checar(not p.erros_pagina(), f"Relatório de notas (avaliador) abriu ({dt:.1f}s)", "Erro no relatório de notas")
            t.foto()

    def r09_categorias(self):
        p = self.como_professor()
        with self.t("R09", "Categorias de nota e forma de agregação", p, "Professor") as t:
            p.get(f"grade/edit/tree/index.php?id={self.cid}")
            txt = p.texto_pagina().replace("\n", " ")
            for cat in ("Trabalhos", "Provas"):
                t.checar(cat in txt, f"Categoria '{cat}' existe", f"Categoria '{cat}' não encontrada", nivel=AVISO)
            agreg = re.findall(r"(Soma das notas \(Natural\)|Média ponderada das notas|Média das notas|Média ponderada simples"
                               r"|Maior nota|Menor nota|Mediana|Moda)", txt)
            t.info("Formas de agregação encontradas: " + ", ".join(dict.fromkeys(agreg)))
            esp = self.op.get("agregacao_esperada")
            if esp:
                t.checar(esp in agreg, f"Agregação esperada '{esp}' está em uso",
                         f"Agregação esperada '{esp}' não encontrada (encontradas: {', '.join(set(agreg))})", nivel=AVISO)
            # confere total = soma das categorias (Natural)
            cats = {}
            for cat in self.reg.meta.get("categorias_notas", {}):
                mm = re.search(rf"{cat}\s+total[^\d]*([\d,]+)", txt, re.I)
                if mm:
                    cats[cat] = float(mm.group(1).replace(",", "."))
            if cats:
                t.info("Máximo por categoria: " + ", ".join(f"{k}={v}" for k, v in cats.items()))
            t.foto()
        a = self.como_aluno()
        with self.t("R09", "Relatório de notas do estudante (cálculo da média)", a, "Estudante") as t:
            dt = a.get(f"grade/report/user/index.php?id={self.cid}")
            if a.erros_pagina():
                t.falha(f"Erro no relatório do usuário: {a.erros_pagina()[0][:150]}")
            txt = a.texto_pagina()
            t.checar(re.search(r"Total do curso|Course total", txt), f"Relatório do estudante abriu com Total do curso ({dt:.1f}s)",
                     "Relatório de notas do estudante sem 'Total do curso'")
            for item in ("Tarefa", "Questionário"):
                t.checar(item in txt, f"Item '{item}' visível ao estudante", f"Item '{item}' não aparece para o estudante",
                         nivel=AVISO)
            if self.nota_tarefa is not None:
                linha = a.js("const r=[...document.querySelectorAll('table.user-grade tr, table.generaltable tr')]"
                             ".find(r=>r.innerText.includes('Tarefa'));return r?r.innerText.replace(/\s+/g,' '):''")
                t.checar(re.search(r"3[,.]50?", linha or ""), f"Nota da Tarefa (3,5) aparece no quadro do estudante: {linha[:120]}",
                         f"Nota da Tarefa não aparece corretamente no quadro do estudante: {linha[:120]}")
                total = a.js("const r=[...document.querySelectorAll('table.user-grade tr, table.generaltable tr')]"
                             ".find(r=>/Total do curso|Course total/.test(r.innerText));return r?r.innerText.replace(/\s+/g,' '):''")
                esperado = self.nota_tarefa + (self.tentativa_quiz or 0)
                t.checar(re.search(str(esperado).replace(".", "[,.]"), total or ""),
                         f"Total do curso calculado corretamente ({esperado}): {total[:120]}",
                         f"Total do curso diferente do esperado ({esperado} = soma das notas obtidas): {total[:120]}")
                cats = a.js("return [...document.querySelectorAll('table.user-grade tr, table.generaltable tr')]"
                            ".filter(r=>/Trabalhos|Provas/.test(r.innerText) && /total/i.test(r.innerText)).map(r=>r.innerText.replace(/\s+/g,' '))")
                for c in cats or []:
                    t.info(f"Total da categoria: {c[:120]}")
            if self.tentativa_quiz is not None:
                t.checar(re.search(str(self.tentativa_quiz).replace(".", ",")[:3], txt),
                         f"Nota do questionário ({self.tentativa_quiz}) aparece no relatório",
                         "Nota do questionário não aparece no relatório do estudante", nivel=AVISO)
            t.foto()
        self.como_professor()

    # ================================================================== R10
    def r10_forum_avisos(self):
        p = self.como_professor()
        with self.t("R10", "Publicar mensagem de boas-vindas no Fórum de Avisos", p, "Professor") as t:
            if not self.op.get("permitir_alteracoes", True):
                t.na("Alterações desativadas")
                return
            ativ = [x for x in p.atividades_curso(self.cid) if x["tipo"] == "forum" and re.search(r"Avisos|Announcements", x["nome"])]
            if not ativ:
                t.falha("Fórum de Avisos não encontrado no curso")
                return
            cm = ativ[0]["cmid"]
            p.get(f"mod/forum/view.php?id={cm}")
            add = [b for b in p.acha("a.btn, button") if re.search(r"Adicionar (um novo )?(tópico|aviso)|Add (discussion|announcement)", b.text)]
            if not add:
                t.falha("Botão para adicionar aviso não encontrado")
                return
            p.clicar(add[0])
            time.sleep(1)
            avancado = [b for b in p.acha("button, a, input[type=submit]") if re.search(r"^Avançado$|^Advanced$",
                                                                                          (b.text or b.get_attribute('value') or '').strip())]
            if avancado:
                p.clicar(avancado[0])
            p.espera("#id_subject")
            p.expandir_formulario()
            assunto = f"Boas-vindas! (teste automatizado {time.strftime('%d/%m %H:%M')})"
            p.preencher("#id_subject", assunto)
            p.editor("id_message", "<p>Sejam bem-vindos à disciplina! Esta mensagem foi publicada por um teste automatizado.</p>")
            if p.existe("#id_mailnow"):
                p.marcar("#id_mailnow", True)
                t.ok("Opção 'Enviar notificações sem atraso' marcada")
            p.clicar("#id_submitbutton")
            t.verificar_pagina()
            p.get(f"mod/forum/view.php?id={cm}")
            t.checar(assunto[:20] in p.texto_pagina(), "Aviso publicado aparece na lista do fórum",
                     "Aviso publicado NÃO aparece no fórum")
            self.reg.meta["aviso_assunto"] = assunto
            t.foto()
        with self.t("R10", "Notificação/e-mail do aviso", p, "Professor") as t:
            if self.modo == "conta":
                a = self.aluno
                ok = False
                for _ in range(6):
                    a.get("message/output/popup/notifications.php")
                    if self.reg.meta.get("aviso_assunto", "")[:20] in a.texto_pagina():
                        ok = True
                        break
                    time.sleep(10)
                t.checar(ok, "Estudante recebeu a notificação do aviso no Moodle",
                         "Notificação ainda não chegou ao estudante (depende do cron; conferir depois)", nivel=AVISO)
            t.manual("Conferir na caixa de e-mail dos participantes se o e-mail do aviso chegou "
                     "(o envio é feito pelo cron do Moodle, normalmente em alguns minutos)")
            p.get(f"course/view.php?id={self.cid}")
            bloco = p.acha(".block_news_items, [data-block='news_items']")
            if bloco:
                t.checar(self.reg.meta.get("aviso_assunto", "")[:15] in bloco[0].text,
                         "Aviso aparece no bloco 'Últimos avisos'", "Aviso não aparece no bloco 'Últimos avisos'", nivel=AVISO)

    # ================================================================== R11
    def _botao_feito(self, nav):
        """Botão de conclusão manual da Aula 1 na página do curso: (elemento, feito?)"""
        nav.get(f"course/view.php?id={self.cid}")
        b = nav.acha(f"#module-{self.cm['pagina_aula1']} button[data-action='toggle-manual-completion']")
        if not b:
            return None, None
        return b[0], "undo" in (b[0].get_attribute("data-toggletype") or "")

    def _liberar_aula2(self, nav):
        """Conclui a Aula 1: 'Marcar como feito' (conclusão manual) ou visualização da página."""
        nav.get(f"mod/page/view.php?id={self.cm['pagina_aula1']}")
        b, feito = self._botao_feito(nav)
        if b is not None and not feito:
            nav.clicar(b)
            time.sleep(2)

    def _secao_aula2(self, nav):
        nav.get(f"course/view.php?id={self.cid}")
        return nav.js("const s=[...document.querySelectorAll('li.section, li.course-section')]"
                      ".find(x=>(x.getAttribute('data-sectionname')||'').includes('Aula 2'));"
                      "return s ? {txt: s.innerText.slice(0,800), links: s.querySelectorAll("
                      "'li.activity a.aalink, li.activity .activityname a').length} : null")

    def r11_restricoes(self):
        cm1 = self.cm["pagina_aula1"]
        p = self.prof
        with self.t("R11", "Conclusão manual na Aula 1 (permite repetir o teste)", p, "Professor") as t:
            if self.resetar_conclusao is None:
                t.na("Função indisponível")
            else:
                mudou = self.resetar_conclusao("pagina_aula1")
                t.ok("Aula 1 configurada para conclusão manual ('Marcar como feito')" if mudou
                     else "Aula 1 já está com conclusão manual")
                t.verificar_pagina()
        with self.t("R11", "Restrição configurada na Aula 2 (visão do professor)", p, "Professor") as t:
            p.get(f"course/view.php?id={self.cid}")
            info = p.js("const s=[...document.querySelectorAll('li.section, li.course-section')]"
                        ".find(x=>(x.getAttribute('data-sectionname')||'').includes('Aula 2'));"
                        "const a=s&&s.querySelector('.availabilityinfo, [data-region=availabilityinfo], .section_availability');"
                        "return a?a.innerText:null")
            t.checar(info, f"Professor vê a regra de restrição da Aula 2: \"{(info or '').strip()[:150]}\"",
                     "Professor não vê nenhuma regra de restrição na Aula 2")
            t.foto()

        a = self.como_aluno()
        with self.t("R11", "Restrição de acesso: Aula 2 bloqueada antes de concluir a Aula 1", a, "Estudante") as t:
            b, feito = self._botao_feito(a)
            concl_txt = a.js("const m=document.querySelector('#module-%s');return m?m.innerText:''" % cm1) or ""
            if b is None and re.search(r"Concluído|Feito|Done", concl_txt):
                t.na("A Aula 1 não está com conclusão manual (não foi possível alterá-la) e já consta como concluída "
                     "pelo estudante, então o bloqueio não pode ser repetido nesta execução.")
                t.foto()
            elif b is None and not re.search(r"Concluído|Feito|Done", concl_txt):
                sec = self._secao_aula2(a)
                aviso = re.search(r"(Disponível se|Não disponível|Not available|Available if|a menos que)[^\n]*", (sec or {}).get("txt", ""))
                t.checar(aviso, f"Aula 2 mostra aviso de restrição: \"{aviso.group(0)[:120] if aviso else ''}\"",
                         "Aula 2 não mostra aviso de restrição para o estudante")
                t.checar(sec and sec["links"] == 0, "Atividades da Aula 2 não estão clicáveis",
                         "Atividades da Aula 2 continuam clicáveis antes da conclusão")
                t.foto()
            else:
                if feito:
                    a.clicar(b)
                    time.sleep(2)
                    t.info("Estudante desmarcou 'Feito' da Aula 1 para repetir o teste")
                b, feito = self._botao_feito(a)
                t.checar(not feito, "Aula 1 está como NÃO concluída", "Não foi possível desmarcar a conclusão da Aula 1")
                sec = self._secao_aula2(a)
                if not sec:
                    t.falha("Seção 'Aula 2' não encontrada para o estudante")
                else:
                    aviso = re.search(r"(Disponível se|Não disponível|Not available|Available if|Disponível somente|Restrito|a menos que)[^\n]*", sec["txt"])
                    t.checar(aviso, f"Aula 2 mostra aviso de restrição: \"{aviso.group(0)[:120] if aviso else ''}\"",
                             "Aula 2 não mostra aviso de restrição para o estudante")
                    t.checar(sec["links"] == 0, "Atividades da Aula 2 não estão clicáveis",
                             f"{sec['links']} atividade(s) da Aula 2 continuam clicáveis antes da conclusão")
                t.foto()
                a.get(f"mod/assign/view.php?id={self.cm['tarefa']}")
                bloqueado = re.search(r"não está disponível|not available|Acesso restrito|indisponível|Sorry|Não disponível",
                                      a.texto_pagina(), re.I) or "course/view.php" in a.d.current_url
                t.checar(bloqueado, "Acesso direto à Tarefa (pela URL) é bloqueado",
                         "Tarefa da Aula 2 abre pela URL direta mesmo sem concluir a Aula 1")
                if bloqueado:
                    t.foto()
        with self.t("R11", "Concluir Aula 1 ('Marcar como feito') libera a Aula 2", a, "Estudante") as t:
            self._liberar_aula2(a)
            b, feito = self._botao_feito(a)
            if b is None:  # conclusão por visualização
                concl_txt = a.js("const m=document.querySelector('#module-%s');return m?m.innerText:''" % cm1) or ""
                feito = bool(re.search(r"Concluído|Feito|Done", concl_txt))
            t.checar(feito, "Aula 1 consta como concluída pelo estudante", "Aula 1 não ficou como concluída")
            sec = self._secao_aula2(a)
            t.checar(sec and sec["links"] > 0, f"Aula 2 liberada: {sec['links'] if sec else 0} atividade(s) clicáveis",
                     "Aula 2 continua bloqueada após concluir a Aula 1")
            a.get(f"mod/assign/view.php?id={self.cm['tarefa']}")
            t.checar("mod/assign/view.php" in a.d.current_url and not re.search(
                r"não está disponível|not available|Acesso restrito", a.texto_pagina(), re.I),
                "Tarefa acessível após concluir a Aula 1", "Tarefa continua inacessível")
            t.foto()
        with self.t("R11", "Relatório de conclusão de atividades (professor)", p, "Professor") as t:
            dt = p.get(f"report/progress/index.php?course={self.cid}")
            erros = [e for e in p.erros_pagina() if "Não há estudantes" not in e]
            if erros:
                t.falha(f"Erro no relatório de progresso: {erros[0][:150]}")
            else:
                t.ok(f"Relatório de conclusão de atividades abriu ({dt:.1f}s)")
                if self.aluno_nome:
                    linha = p.js("const r=[...document.querySelectorAll('table tr')].find(r=>r.innerText.includes(arguments[0]));"
                                 "return r?r.innerHTML:''", self.aluno_nome)
                    t.checar(linha and re.search(r"completion-y|Concluído|conclu", linha, re.I),
                             f"Relatório mostra a Aula 1 concluída por {self.aluno_nome}",
                             f"Relatório não mostra a conclusão de {self.aluno_nome}", nivel=AVISO)
            t.foto()

    # ================================================================== X02
    def x02_interacao(self):
        cmf = self.cm.get("forum_duvidas")
        if not cmf or not self.op.get("permitir_alteracoes", True):
            return
        a = self.como_aluno()
        assunto = f"Dúvida do estudante {time.strftime('%H:%M:%S')}"
        with self.t("X02", "Estudante publica dúvida no fórum", a, "Estudante") as t:
            a.get(f"mod/forum/view.php?id={cmf}")
            add = [b for b in a.acha("a.btn, button") if re.search(r"Adicionar (um novo )?tópico|Add (a new )?discussion", b.text)]
            if not add:
                t.falha("Estudante não tem o botão para criar tópico no fórum")
                return self.como_professor()
            a.clicar(add[0])
            time.sleep(1)
            if a.existe("#id_subject") or a.existe("input[name=subject]"):
                a.preencher("#id_subject" if a.existe("#id_subject") else "input[name=subject]", assunto)
                if a.existe("textarea[name=message]") and not a.existe("#id_message"):
                    a.preencher("textarea[name=message]", "Professor, tenho uma dúvida sobre a Aula 1.")
                else:
                    a.editor("id_message", "<p>Professor, tenho uma dúvida sobre a Aula 1.</p>")
                env = [b for b in a.acha("#id_submitbutton, form button[type=submit], form input[type=submit]")
                       if re.search(r"Postar|Post|Enviar", b.text or b.get_attribute("value") or "")]
                a.clicar(env[0] if env else "#id_submitbutton")
            a.get(f"mod/forum/view.php?id={cmf}")
            t.checar(assunto in a.texto_pagina(), "Dúvida publicada pelo estudante", "Dúvida do estudante não aparece no fórum")
            t.foto()
        p = self.como_professor()
        with self.t("X02", "Professor responde a dúvida", p, "Professor") as t:
            p.get(f"mod/forum/view.php?id={cmf}")
            link = [l for l in p.acha("a") if assunto in (l.text or "")]
            if not link:
                t.falha("Professor não encontrou a dúvida do estudante")
                return
            p.clicar(link[0])
            resp = [b for b in p.acha("a, button") if re.search(r"^Responder$|^Reply$", (b.text or "").strip())]
            if not resp:
                t.falha("Botão 'Responder' não encontrado")
                return
            p.clicar(resp[0])
            time.sleep(1)
            caixa = p.acha("textarea[name='post'], [data-region='post-message'] textarea, textarea[id^='id_message']")
            if caixa:
                caixa[0].send_keys("Resposta do professor: a Aula 2 é liberada após concluir a Aula 1.")
                env = [b for b in p.acha("button[data-action='forum-inpage-submit'], button") if
                       re.search(r"Enviar|Postar|Post to forum|Submit", b.text or "") and b.is_displayed()]
                p.clicar(env[0])
                time.sleep(2)
            p.get(p.d.current_url)
            t.checar("Resposta do professor" in p.texto_pagina(), "Resposta do professor publicada",
                     "Resposta do professor não apareceu")
            t.foto()
        a = self.como_aluno()
        with self.t("X02", "Estudante vê a resposta do professor", a, "Estudante") as t:
            a.get(f"mod/forum/view.php?id={cmf}")
            link = [l for l in a.acha("a") if assunto in (l.text or "")]
            if link:
                a.clicar(link[0])
            t.checar("Resposta do professor" in a.texto_pagina(), "Estudante visualiza a resposta do professor",
                     "Estudante não vê a resposta do professor")
        self.como_professor()

        # avaliação da tarefa (somente com conta de aluno real)
        p = self.prof
        with self.t("X02", "Professor avalia a tarefa e o estudante vê a nota/feedback", p, "Professor") as t:
            if self.modo != "conta":
                t.na("Requer uma conta de estudante real (no 'Mudar papel' o professor não aparece na lista de envios)")
                p.get(f"mod/assign/view.php?id={self.cm['tarefa']}&action=grading")
                t.checar(not p.erros_pagina(), "Página de envios/avaliação da tarefa abre para o professor",
                         "Erro na página de avaliação da tarefa")
                return
            if not self.aluno_id:
                t.falha("Não consegui identificar o ID do estudante para abrir o avaliador")
                return
            p.get(f"mod/assign/view.php?id={self.cm['tarefa']}&action=grader&userid={self.aluno_id}")
            p.espera("#id_grade", t=40)
            time.sleep(3)
            nome_tela = p.js("var e=document.querySelector('[data-region=user-info] , .user-info, [data-region=\"user-selector\"]');"
                             "return e?e.innerText.trim():''")
            t.info(f"Avaliador aberto para: {nome_tela[:80]}")
            p.preencher("#id_grade", "3,5")
            p.editor("id_assignfeedbackcomments_editor", "<p>Bom trabalho! (feedback automatizado)</p>")
            p.clicar("button[name='savechanges']")
            time.sleep(4)
            p.get(f"mod/assign/view.php?id={self.cm['tarefa']}&action=grading")
            linha = p.js("const r=[...document.querySelectorAll('table.generaltable tbody tr')].find(r=>r.innerText.includes(arguments[0]));"
                         "return r?r.innerText.replace(/\\s+/g,' '):''", self.aluno_nome)
            if not re.search(r"3,50", linha or ""):
                t.falha(f"Nota não ficou registrada para o estudante na tabela de envios: {linha[:150]}")
                return
            t.ok("Nota 3,5 e feedback salvos no avaliador")
            self.nota_tarefa = 3.5
            a = self.aluno
            a.get(f"mod/assign/view.php?id={self.cm['tarefa']}")
            txt = a.texto_pagina()
            t.checar("3,5" in txt or "3.5" in txt, "Estudante vê a nota 3,5", "Estudante não vê a nota")
            t.checar("Bom trabalho" in txt, "Estudante vê o feedback do professor", "Estudante não vê o feedback")
            t.foto()

    # ================================================================== X03
    def x03_calendario(self):
        a = self.como_aluno()
        with self.t("X03", "Prazo da tarefa no calendário e na linha do tempo", a, "Estudante") as t:
            a.get(f"calendar/view.php?view=upcoming&course={self.cid}")
            txt = a.texto_pagina()
            t.checar("Tarefa" in txt, "Prazo da Tarefa aparece em 'Próximos eventos' do calendário",
                     "Prazo da Tarefa NÃO aparece no calendário", nivel=AVISO)
            t.verificar_pagina()
            t.foto()
            a.get("my/")
            time.sleep(3)
            tl = a.acha("[data-region='timeline'], .block_timeline")
            if tl:
                t.checar("Tarefa" in tl[0].text or self.envio_feito, "Tarefa aparece na Linha do tempo do Painel",
                         "Tarefa não aparece na Linha do tempo", nivel=AVISO)
        self.como_professor()

    # ================================================================== X04
    def x04_responsivo(self):
        a = self.como_aluno()
        paginas = [("Curso", f"course/view.php?id={self.cid}"),
                   ("Plano de Ensino", f"mod/page/view.php?id={self.cm['plano_pagina']}"),
                   ("Tarefa", f"mod/assign/view.php?id={self.cm['tarefa']}"),
                   ("Questionário", f"mod/quiz/view.php?id={self.cm['quiz']}")]
        for disp, (w, h) in (("Celular", (390, 844)), ("Tablet", (820, 1180))):
            with self.t("X04", f"Layout em {disp} ({w}x{h})", a, "Estudante") as t:
                a.d.set_window_size(w, h)
                try:
                    for nome, url in paginas:
                        a.get(url)
                        larg = a.js("return [document.documentElement.scrollWidth, window.innerWidth]")
                        if larg[0] > larg[1] + 5:
                            t.aviso(f"{nome}: rolagem horizontal (conteúdo {larg[0]}px > tela {larg[1]}px)")
                        else:
                            t.ok(f"{nome}: sem rolagem horizontal")
                    a.get(f"course/view.php?id={self.cid}")
                    menu = a.acha("[data-toggler='drawers'], .drawer-toggler button, button[data-action='toggle-drawer']")
                    t.checar(menu, "Botão do índice do curso/menu disponível", "Sem botão para abrir o índice do curso", nivel=AVISO)
                    t.foto()
                finally:
                    a.d.set_window_size(1440, 1000)
        self.como_professor()

    # ================================================================== X05 / X06
    def x05_x06_resumo(self, navs):
        with self.t("X05", "Erros de JavaScript no console (todas as páginas testadas)", None, "Sistema") as t:
            ej = self.reg.meta.get("erros_js", [])
            if ej:
                # agrupa por mensagem (sem o número de linha), mostrando em quantas páginas apareceu
                grupos = {}
                for e in ej:
                    for msg in e["erros"]:
                        chave = re.sub(r"\s\d+:\d+\s", " ", re.sub(r"^\S+\s", "", msg))[:160]
                        grupos.setdefault(chave, set()).add(e["pagina"])
                for msg, pags in sorted(grupos.items(), key=lambda x: -len(x[1]))[:12]:
                    t.aviso(f"Em {len(pags)} página(s): {msg}", print_=False)
            else:
                t.ok("Nenhum erro de JavaScript relevante registrado")
        with self.t("X06", "Tempo de carregamento das páginas", None, "Sistema") as t:
            tempos = []
            for n in navs:
                tempos += n.tempos
            if not tempos:
                t.na("Sem medições")
                return
            lim = float(self.op.get("tempo_lento_segundos", 5))
            lentas = sorted([x for x in tempos if x[1] > lim], key=lambda x: -x[1])
            media = sum(x[1] for x in tempos) / len(tempos)
            t.info(f"{len(tempos)} carregamentos medidos; média {media:.2f}s; mais lento {max(x[1] for x in tempos):.1f}s")
            for u, s in lentas[:10]:
                t.aviso(f"Página lenta ({s:.1f}s): {u[:100]}", print_=False)
            t.dados["tempos"] = tempos
            t.dados["media"] = round(media, 2)
