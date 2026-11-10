"""Fase de preparação: o professor monta no curso de teste o conteúdo exigido pelo roteiro.

Tudo é criado com o prefixo configurado (ex.: "[AUTO]") e é idempotente: se o item já existe,
é reaproveitado. Use `executar.py --limpar` para remover tudo que foi criado.
"""
import datetime
import json
import re
import time

from .core import MoodleError
from .resultado import FALHA


class Preparador:
    def __init__(self, m, reg, course_id, arquivos, prefixo="[AUTO]"):
        self.m, self.reg, self.cid, self.arq, self.p = m, reg, course_id, arquivos, prefixo
        self.cm = {}  # chave -> cmid

    def nome(self, n):
        return f"{self.p} {n}"

    # ------------------------------------------------------------------ util
    def _existentes(self):
        return {a["nome"]: a for a in self.m.atividades_curso(self.cid)}

    def _achar(self, nome, existentes):
        for n, a in existentes.items():
            if n.startswith(nome) or nome in n:
                return a
        return None

    def _conclusao_ao_ver(self):
        if self.m.existe("#id_completion_2"):
            self.m.clicar("#id_completion_2")
            time.sleep(0.3)
            if self.m.existe("#id_completionview"):
                self.m.marcar("#id_completionview", True)
            return True
        return False

    def resetar_conclusao(self, chave):
        """Garante conclusão MANUAL na atividade (o estudante pode marcar/desmarcar 'Feito'),
        o que torna o teste de restrição repetível. Desde o Moodle 4.3 a conclusão por
        visualização não é zerada pelo 'Desbloquear opções de conclusão'.
        Retorna True se alterou a configuração."""
        m = self.m
        m.get(f"course/modedit.php?update={self.cm[chave]}&return=1")
        m.expandir_formulario()
        if m.existe("#id_completion_1") and m.um("#id_completion_1").is_selected():
            m.clicar("#id_cancel")
            return False
        if m.existe("#id_unlockcompletion"):
            m.clicar("#id_unlockcompletion")
            m.expandir_formulario()
            erros = m.erros_pagina()
            if erros:
                raise MoodleError("O botão 'Desbloquear opções de conclusão' gerou erro no Moodle: " + erros[0][:250])
        if not m.existe("#id_completion_1"):
            raise MoodleError("Opção de conclusão manual não disponível no formulário")
        m.clicar("#id_completion_1")
        self._sem_notificacao()
        m.salvar_form()
        return True

    def _sem_notificacao(self):
        if self.m.existe("#id_coursecontentnotification"):
            self.m.marcar("#id_coursecontentnotification", False)

    def _salvar_e_cmid(self):
        self._sem_notificacao()
        self.m.salvar_form(voltar_curso=False)
        url = self.m.d.current_url
        if "modedit.php" in url:
            raise MoodleError("Formulário não foi salvo (continua na página de edição)")
        import re
        mm = re.search(r"[?&]id=(\d+)", url)
        return mm.group(1) if mm else None

    def _data(self, prefixo_campo, dt):
        m = self.m
        m.marcar(f"#id_{prefixo_campo}_enabled", True)
        for campo, v in (("day", dt.day), ("month", dt.month), ("year", dt.year), ("hour", dt.hour),
                         ("minute", dt.minute - dt.minute % 5)):
            sel = f"#id_{prefixo_campo}_{campo}"
            if m.existe(sel):
                m.selecionar(sel, v)

    # ------------------------------------------------------------------ curso
    def configurar_curso(self, t):
        """Garante acompanhamento de conclusão ativo e livro de notas visível ao estudante."""
        m = self.m
        m.get(f"course/edit.php?id={self.cid}")
        m.expandir_formulario()
        mudou = []
        orig = {"format": m.js("return document.getElementById('id_format').value"),
                "enablecompletion": m.js("var e=document.getElementById('id_enablecompletion');return e?e.value:null")}
        self.reg.meta["formato_original"] = orig["format"]
        t.info(f"Formato atual do curso: {orig['format']}")
        if orig["enablecompletion"] == "0":
            m.selecionar("#id_enablecompletion", 1)
            mudou.append("acompanhamento de conclusão ativado")
        if m.existe("#id_coursedisplay") and m.js("return document.getElementById('id_coursedisplay').value") != "0":
            m.selecionar("#id_coursedisplay", 0)
            mudou.append("layout 'todas as seções em uma página'")
        if m.existe("#id_showcompletionconditions"):
            m.selecionar("#id_showcompletionconditions", 1)
        if m.existe("#id_showgrades"):
            m.selecionar("#id_showgrades", 1)
        botao = "#id_saveanddisplay" if m.existe("#id_saveanddisplay") else "#id_submitbutton"
        m.clicar(botao)
        t.ok("Configurações do curso salvas" + (": " + ", ".join(mudou) if mudou else ""))

    def secoes(self, t):
        nomes = ["Apresentação", "Aula 1", "Aula 2", "Avaliação"]
        secs = self.m.secoes_curso(self.cid)
        while len(secs) < 5:
            # adiciona seção pelo link "Adicionar seção" no modo de edição
            self.m.edicao(True)
            add = self.m.acha("[data-action='addSection'], a.add-section, .add-sections a")
            if not add:
                raise MoodleError("Não há seções suficientes e não achei o botão de adicionar seção")
            self.m.clicar(add[-1])
            secs = self.m.secoes_curso(self.cid)
        self.secids = {}
        for i, n in enumerate(nomes, start=1):
            alvo = self.nome(n)
            self.secids[n] = secs[i]["id"]
            if secs[i]["nome"] != alvo:
                self.reg.meta.setdefault("nomes_secoes_originais", {})[secs[i]["id"]] = secs[i]["nome"]
                self.m.get(f"course/editsection.php?id={secs[i]['id']}&sr=0")
                if self.m.existe("#id_name_customize"):
                    self.m.marcar("#id_name_customize", True)
                    self.m.preencher("#id_name_value", alvo)
                else:
                    self.m.preencher("#id_name", alvo)
                self.m.clicar("#id_submitbutton")
        t.ok("Seções nomeadas: " + ", ".join(self.nome(n) for n in nomes))

    # ------------------------------------------------------------------ módulos
    def label(self, sec, chave, html):
        ex = self._existentes()
        marca = f"AUTO-{chave}"
        titulo = re.sub(r"<[^>]+>", "", re.search(r"<h3>(.*?)</h3>", html).group(1)).strip()
        for a in ex.values():
            if a["tipo"] == "label" and (marca in (a.get("html") or "") or titulo in (a.get("texto") or "")):
                self.cm[chave] = a["cmid"]
                return a["cmid"], False
        self.m.abrir_form_modulo(self.cid, "label", sec)
        self.m.editor("id_introeditor", html.replace("{MARCA}", marca))
        self._sem_notificacao()
        self.m.salvar_form()
        ex = self._existentes()
        for a in ex.values():
            if a["tipo"] == "label" and (marca in (a.get("html") or "") or titulo in (a.get("texto") or "")):
                self.cm[chave] = a["cmid"]
                return a["cmid"], True
        raise MoodleError(f"Rótulo {chave} não apareceu no curso após salvar")

    def modulo(self, chave, tipo, sec, nome, preencher):
        nome = self.nome(nome)
        a = self._achar(nome, self._existentes())
        if a:
            self.cm[chave] = a["cmid"]
            return a["cmid"], False
        self.m.abrir_form_modulo(self.cid, tipo, sec)
        self.m.preencher("#id_name", nome)
        preencher()
        cmid = self._salvar_e_cmid()
        a = self._achar(nome, self._existentes())
        self.cm[chave] = a["cmid"] if a else cmid
        return self.cm[chave], True

    def criar_tudo(self, t):
        """Cria todo o conteúdo do curso de teste. Retorna dicionário chave->cmid."""
        m, arq = self.m, self.arq
        criados = []
        S = {n: i for i, n in enumerate(["", "Apresentação", "Aula 1", "Aula 2", "Avaliação"])}

        def reg(r, chave):
            if r[1]:
                criados.append(chave)

        # --- Apresentação
        reg(self.label(S["Apresentação"], "rotulo_boasvindas", """
            <span class="sr-only visually-hidden">{MARCA}</span>
            <h3>Boas-vindas à disciplina</h3>
            <p>Este curso foi preparado por um <strong>teste automatizado</strong>.</p>
            <h4>Como estudar</h4>
            <ol><li>Leia o Plano de Ensino</li><li>Estude a Aula 1</li><li>Faça a Tarefa e o Questionário</li></ol>
            <div class="alert alert-warning" role="alert"><strong>Aviso:</strong> a Aula 2 só é liberada
            após concluir a Aula 1.</div>"""), "rotulo_boasvindas")

        def f_plano():
            m.editor("id_page", f"""
                <h3>Plano de Ensino</h3>
                <h4>Cronograma</h4>
                <table class="table" border="1"><thead><tr><th>Semana</th><th>Conteúdo</th><th>Entrega</th></tr></thead>
                <tbody><tr><td>1</td><td>Aula 1</td><td>-</td></tr><tr><td>2</td><td>Aula 2</td><td>Tarefa</td></tr>
                <tr><td>3</td><td>Avaliação</td><td>Questionário</td></tr></tbody></table>
                <h4>Critérios de avaliação</h4>
                <ul><li>Tarefa: 4,0 pontos</li><li>Questionário: 6,0 pontos</li><li><strong>Total: 10,0 pontos</strong></li></ul>
                <h4>Links úteis</h4>
                <ul><li><a href="https://www.unb.br" target="_blank">Portal da UnB</a></li>
                <li><a href="https://docs.moodle.org/pt_br/" target="_blank">Documentação do Moodle</a></li>
                <li><a href="https://www.youtube.com/watch?v=C3faCO1t56c" target="_blank">Vídeo: configuração do Quadro de Notas</a></li></ul>""")
        reg(self.modulo("plano_pagina", "page", S["Apresentação"], "Plano de Ensino", f_plano), "plano_pagina")

        def f_plano_pdf():
            m.upload_filemanager(arq["plano_v1"])
            m.selecionar("#id_display", 5)  # Abrir
            if m.existe("#id_showsize"):
                m.marcar("#id_showsize", True)
                m.marcar("#id_showtype", True)
        reg(self.modulo("plano_pdf", "resource", S["Apresentação"], "Plano de Ensino (PDF)", f_plano_pdf), "plano_pdf")

        def f_forum():
            m.selecionar("#id_type", "general")
            m.editor("id_introeditor", "<p>Espaço para dúvidas entre estudantes e professor.</p>")
        reg(self.modulo("forum_duvidas", "forum", S["Apresentação"], "Fórum de Dúvidas", f_forum), "forum_duvidas")

        # --- Aula 1
        reg(self.label(S["Aula 1"], "rotulo_aula1", """<span class="sr-only visually-hidden">{MARCA}</span><h3>Aula 1 - Introdução</h3>
            <p>Objetivo: apresentar os conceitos iniciais.</p><h4>Materiais</h4>"""), "rotulo_aula1")

        def f_res(caminho, display):
            def f():
                m.upload_filemanager(caminho)
                m.selecionar("#id_display", display)
                if m.existe("#id_showsize"):
                    m.marcar("#id_showsize", True)
                    m.marcar("#id_showtype", True)
            return f
        reg(self.modulo("pdf_texto", "resource", S["Aula 1"], "Aula 1 - Texto base (PDF)",
                        f_res(arq["texto_base"], 1)), "pdf_texto")          # incorporar
        reg(self.modulo("pdf_leitura", "resource", S["Aula 1"], "Aula 1 - Leitura complementar (PDF)",
                        f_res(arq["leitura"], 6)), "pdf_leitura")           # pop-up
        reg(self.modulo("pptx", "resource", S["Aula 1"], "Aula 1 - Slides (PPTX)",
                        f_res(arq["slides"], 4)), "pptx")                    # forçar download

        def f_url(u, display):
            def f():
                m.preencher("#id_externalurl", u)
                m.selecionar("#id_display", display)
            return f
        reg(self.modulo("url_site", "url", S["Aula 1"], "Link - Portal UnB", f_url("https://www.unb.br", 6)), "url_site")
        reg(self.modulo("url_video", "url", S["Aula 1"], "Vídeo - Quadro de Notas (YouTube)",
                        f_url("https://www.youtube.com/watch?v=C3faCO1t56c", 0)), "url_video")

        def f_video():
            m.editor("id_page", """<h3>Vídeo da aula</h3>
                <p><iframe width="560" height="315" src="https://www.youtube.com/embed/C3faCO1t56c"
                 title="Vídeo da aula" allowfullscreen></iframe></p>
                <p>Ao visualizar esta página a Aula 1 é marcada como concluída e a Aula 2 é liberada.</p>""")
            self._conclusao_ao_ver()
        reg(self.modulo("pagina_aula1", "page", S["Aula 1"], "Aula 1 - Vídeo e conclusão", f_video), "pagina_aula1")

        # --- categorias de notas antes das atividades avaliativas
        self.categorias = self.categorias_notas()

        # --- Aula 2 (restrita)
        reg(self.label(S["Aula 2"], "rotulo_aula2", """<span class="sr-only visually-hidden">{MARCA}</span><h3>Aula 2 - Aprofundamento</h3>
            <p>Esta seção é liberada após a conclusão da Aula 1.</p>"""), "rotulo_aula2")
        prazo = (datetime.datetime.now() + datetime.timedelta(days=7)).replace(hour=23, minute=55)
        self.reg.meta["prazo_tarefa"] = prazo.strftime("%d/%m/%Y %H:%M")

        def f_tarefa():
            m.editor("id_introeditor", "<p><strong>Instrução:</strong> envie um arquivo PDF (até 1 MB) "
                                       "e escreva um breve comentário no texto online.</p>")
            m.marcar("#id_alwaysshowdescription", True) if m.existe("#id_alwaysshowdescription") else None
            self._data("duedate", prazo)
            if m.existe("#id_cutoffdate_enabled"):
                m.marcar("#id_cutoffdate_enabled", False)
            if m.existe("#id_gradingduedate_enabled"):
                m.marcar("#id_gradingduedate_enabled", False)
            m.marcar("#id_assignsubmission_onlinetext_enabled", True)
            m.marcar("#id_assignsubmission_file_enabled", True)
            m.selecionar("#id_assignsubmission_file_maxfiles", 1)
            m.selecionar("#id_assignsubmission_file_maxsizebytes", 1048576)  # 1 MB
            m.preencher("#id_assignsubmission_file_filetypes", ".pdf,.docx,.pptx")
            m.selecionar("#id_submissiondrafts", 1)
            m.selecionar("#id_grade_modgrade_type", "point")
            m.preencher("#id_grade_modgrade_point", "4")
            if self.categorias.get("Trabalhos"):
                m.selecionar("#id_gradecat", self.categorias["Trabalhos"])
            if m.existe("#id_completion_2"):
                m.clicar("#id_completion_2")
                time.sleep(0.3)
                m.marcar("#id_completionsubmit", True)
        reg(self.modulo("tarefa", "assign", S["Aula 2"], "Tarefa - Envio de arquivo e texto", f_tarefa), "tarefa")

        # --- Avaliação
        def f_quiz():
            m.editor("id_introeditor", "<p>Questionário com 3 questões. Tempo: 10 minutos. 2 tentativas.</p>")
            m.marcar("#id_timelimit_enabled", True)
            m.preencher("#id_timelimit_number", "10")
            m.selecionar("#id_timelimit_timeunit", 60)
            m.selecionar("#id_attempts", 2)
            m.selecionar("#id_grademethod", 1)
            m.selecionar("#id_preferredbehaviour", "deferredfeedback")
            if self.categorias.get("Provas"):
                m.selecionar("#id_gradecat", self.categorias["Provas"])
            # revisão: mostrar nota e respostas logo após a tentativa
            for c in ("attempt", "correctness", "marks", "specificfeedback", "generalfeedback",
                      "rightanswer", "overallfeedback"):
                if m.existe(f"#id_{c}immediately"):
                    m.marcar(f"#id_{c}immediately", True)
        reg(self.modulo("quiz", "quiz", S["Avaliação"], "Questionário", f_quiz), "quiz")

        self.restricao_aula2(t)
        t.info("Itens criados nesta execução: " + (", ".join(criados) or "nenhum (já existiam)"))
        self.reg.meta["cm"] = self.cm
        return self.cm

    # ------------------------------------------------------------------ restrição
    def restricao_aula2(self, t):
        cm = self.cm.get("pagina_aula1")
        secid = self.secids["Aula 2"]
        self.m.get(f"course/editsection.php?id={secid}&sr=0")
        self.m.expandir_formulario()
        atual = self.m.js("var e=document.getElementById('id_availabilityconditionsjson');return e?e.value:null")
        if atual is None:
            t.aviso("Campo de restrição de acesso não encontrado no formulário da seção")
            return
        if cm and f'"cm":{cm}' in (atual or "").replace(" ", ""):
            self.m.clicar("#id_cancel")
            return
        cond = {"op": "&", "c": [{"type": "completion", "cm": int(cm), "e": 1}], "showc": [True]}
        self.m.js("document.getElementById('id_availabilityconditionsjson').value = arguments[0];", json.dumps(cond))
        self.m.clicar("#id_submitbutton")
        t.ok("Restrição configurada: Aula 2 liberada somente após concluir 'Aula 1 - Vídeo e conclusão'")

    # ------------------------------------------------------------------ notas
    def categorias_notas(self):
        m = self.m
        res = {}
        for nome in ("Trabalhos", "Provas"):
            completo = self.nome(nome)
            m.get(f"course/modedit.php?add=assign&type=&course={self.cid}&section=0&return=0&sr=0")
            ops = m.js("var s=document.getElementById('id_gradecat');return s?[...s.options].map(o=>[o.value,o.text]):[]")
            achou = [v for v, tx in ops if tx.strip() == completo]
            if achou:
                res[nome] = achou[0]
                continue
            m.get(f"grade/edit/tree/category.php?courseid={self.cid}&id=0")
            m.expandir_formulario()
            m.preencher("#id_fullname", completo)
            m.selecionar("#id_aggregation", 13)  # Natural
            m.clicar("#id_submitbutton")
            m.get(f"course/modedit.php?add=assign&type=&course={self.cid}&section=0&return=0&sr=0")
            ops = m.js("var s=document.getElementById('id_gradecat');return s?[...s.options].map(o=>[o.value,o.text]):[]")
            achou = [v for v, tx in ops if tx.strip() == completo]
            if achou:
                res[nome] = achou[0]
        self.reg.meta["categorias_notas"] = res
        return res

    # ------------------------------------------------------------------ questões
    def questoes_quiz(self, t):
        """Adiciona 3 questões ao questionário pelo fluxo normal (Adicionar > uma nova questão)."""
        m = self.m
        cmid = self.cm["quiz"]
        m.get(f"mod/quiz/edit.php?cmid={cmid}")
        n = m.js("return document.querySelectorAll('li.slot, .slot').length")
        # nota máxima 6 (Tarefa 4 + Questionário 6 = 10)
        if m.existe("#inputmaxgrade") and m.js("return document.getElementById('inputmaxgrade').value").replace(",", ".") not in ("6", "6.00"):
            m.preencher("#inputmaxgrade", "6")
            m.clicar("input[name=savechanges]")
            t.ok("Nota máxima do questionário definida como 6")
            m.get(f"mod/quiz/edit.php?cmid={cmid}")
        if n >= 3:
            t.ok(f"Questionário já possui {n} questões")
            return True
        questoes = [
            ("truefalse", "VF - Capital", "<p>Brasília é a capital do Brasil.</p>", None),
            ("multichoice", "ME - Soma", "<p>Quanto é 2 + 3?</p>", ["5", "4", "6", "23"]),
            ("shortanswer", "RC - Cor", "<p>Qual a cor do céu em um dia limpo? (uma palavra)</p>", ["azul"]),
        ][n:]
        for qtipo, qnome, qtexto, respostas in questoes:
            m.get(f"mod/quiz/edit.php?cmid={cmid}")
            add = [a for a in m.acha(".add-menu-outer a") if a.text.strip() == "Adicionar"]
            if not add:
                raise MoodleError("Menu 'Adicionar' do questionário não encontrado")
            m.clicar(add[-1])
            time.sleep(0.4)
            m.clicar(m.um("a[data-action='addquestion']"))
            radio = m.espera(f".moodle-dialogue-base input[name=qtype][value={qtipo}]")
            m.clicar(radio)
            sub = [b for b in m.acha(".moodle-dialogue-base input[name=submitbutton]") if b.is_displayed()]
            m.clicar(sub[0])
            if not m.existe("#id_questiontext, textarea[name='questiontext[text]']"):
                t.falha(f"Ao adicionar questão '{qtipo}', o formulário da questão não abriu "
                        f"(página voltou para {m.d.current_url}). " + self._aviso_qbank())
                return False
            m.preencher("#id_name", qnome)
            m.editor("id_questiontext", qtexto)
            if qtipo == "truefalse":
                m.selecionar("#id_correctanswer", 1)
            elif qtipo == "multichoice":
                for i, r in enumerate(respostas):
                    m.editor(f"id_answer_{i}", f"<p>{r}</p>")
                    m.selecionar(f"#id_fraction_{i}", "1.0" if i == 0 else "0.0")
            elif qtipo == "shortanswer":
                m.preencher("#id_answer_0", respostas[0])
                m.selecionar("#id_fraction_0", "1.0")
            m.clicar("#id_submitbutton")
            if m.existe("form.mform #id_questiontext"):
                erros = [e.text for e in m.acha(".invalid-feedback, .error") if e.is_displayed() and e.text.strip()]
                t.falha(f"Questão '{qnome}' não foi salva: {' | '.join(erros)}")
                return False
            t.ok(f"Questão criada: {qnome}")
        return True

    def _aviso_qbank(self):
        txt = self.m.texto_pagina()
        import re
        mm = re.search(r"As tarefas ad hoc.*?concluídas[^.]*\.", txt, re.S)
        return ("Aviso exibido pelo Moodle: " + mm.group(0).replace("\n", " ")) if mm else ""


def limpar(m, course_id, prefixo, reg):
    """Remove atividades e categorias criadas pelo teste e restaura nomes de seções."""
    sk = m.sesskey
    removidos = 0
    for a in m.atividades_curso(course_id):
        if prefixo in a["nome"] or "AUTO-" in (a.get("html") or "") or "Probe" in a["nome"]:
            m.get(f"course/mod.php?delete={a['cmid']}&confirm=1&sesskey={sk}")
            removidos += 1
    reg.log(f"Atividades removidas: {removidos}")
    for s in m.secoes_curso(course_id):
        if s["nome"].startswith(prefixo):
            m.get(f"course/editsection.php?id={s['id']}&sr=0")
            m.preencher("#id_name", "")
            m.clicar("#id_submitbutton")
    return removidos
