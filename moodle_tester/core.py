"""Núcleo: navegador Selenium com helpers de Moodle, captura de erros e prints."""
import os
import re
import time
import json
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    ElementClickInterceptedException, JavascriptException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# Textos que indicam erro do PHP/Moodle na página
PADROES_ERRO = [
    r"Exception - ", r"Erro de programação", r"Coding error detected",
    r"Fatal error", r"Parse error", r"Warning:\s", r"Notice:\s", r"Deprecated:\s",
    r"Stack trace", r"Debug info:", r"Erro de leitura do banco de dados",
    r"Error reading from database", r"Página não encontrada", r"Ocorreu um erro inesperado",
    r"dmlreadexception", r"moodle_exception",
]


class MoodleError(Exception):
    pass


class Browser:
    def __init__(self, base_url, out_dir, headless=True, nome="navegador", timeout=20):
        self.base = base_url.rstrip("/")
        self.out_dir = out_dir
        self.nome = nome
        self.timeout = timeout
        self.prints_dir = os.path.join(out_dir, "prints")
        self.downloads_dir = os.path.abspath(os.path.join(out_dir, "downloads"))
        os.makedirs(self.prints_dir, exist_ok=True)
        os.makedirs(self.downloads_dir, exist_ok=True)

        o = webdriver.ChromeOptions()
        if headless:
            o.add_argument("--headless=new")
        o.add_argument("--window-size=1440,1000")
        o.add_argument("--lang=pt-BR")
        o.add_argument("--disable-notifications")
        o.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        o.add_experimental_option("prefs", {
            "download.default_directory": self.downloads_dir,
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": False,
        })
        self.d = webdriver.Chrome(options=o)
        self.d.set_page_load_timeout(60)
        self.tempos = []  # (url, segundos)

    # ------------------------------------------------------------ básicos
    def url(self, path):
        return path if path.startswith("http") else self.base + "/" + path.lstrip("/")

    def get(self, path, esperar=None):
        t0 = time.time()
        self.d.get(self.url(path))
        self.aguardar_carregar()
        if esperar:
            self.espera(esperar)
        dt = time.time() - t0
        self.tempos.append((self.d.current_url, round(dt, 2)))
        return dt

    def aguardar_carregar(self, extra=0.3):
        try:
            WebDriverWait(self.d, self.timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
        except TimeoutException:
            pass
        # espera requisições AJAX do Moodle (M.util.pending_js)
        try:
            WebDriverWait(self.d, 10).until(lambda d: d.execute_script(
                "return !(window.M && M.util && M.util.pending_js && M.util.pending_js.length)"))
        except Exception:
            pass
        time.sleep(extra)

    def espera(self, css, t=None, visivel=False):
        cond = EC.visibility_of_element_located if visivel else EC.presence_of_element_located
        return WebDriverWait(self.d, t or self.timeout).until(cond((By.CSS_SELECTOR, css)))

    def espera_xpath(self, xp, t=None):
        return WebDriverWait(self.d, t or self.timeout).until(
            EC.presence_of_element_located((By.XPATH, xp)))

    def acha(self, css, base=None):
        return (base or self.d).find_elements(By.CSS_SELECTOR, css)

    def um(self, css, base=None):
        return (base or self.d).find_element(By.CSS_SELECTOR, css)

    def xp(self, xp, base=None):
        return (base or self.d).find_elements(By.XPATH, xp)

    def existe(self, css):
        return len(self.acha(css)) > 0

    def clicar(self, el_ou_css, js_fallback=True):
        el = self.um(el_ou_css) if isinstance(el_ou_css, str) else el_ou_css
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        try:
            el.click()
        except (ElementClickInterceptedException, Exception):
            if not js_fallback:
                raise
            self.d.execute_script("arguments[0].click();", el)
        self.aguardar_carregar()

    def clicar_texto(self, texto, tag="*", base=None):
        el = self.espera_xpath(f"//{tag}[normalize-space()={json.dumps(texto)}]")
        self.clicar(el)

    def preencher(self, css, valor, limpar=True):
        el = self.um(css)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            if limpar:
                el.clear()
            el.send_keys(valor)
        except Exception:
            # campo oculto/coberto (ex.: seção recolhida): define o valor via JavaScript
            self.d.execute_script("""
                const e = arguments[0];
                e.value = (arguments[2] ? '' : e.value) + arguments[1];
                e.dispatchEvent(new Event('input', {bubbles:true}));
                e.dispatchEvent(new Event('change', {bubbles:true}));""", el, valor, limpar)
        return el

    def selecionar(self, css, valor=None, texto=None):
        el = self.um(css)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            s = Select(el)
            if texto is not None:
                s.select_by_visible_text(texto)
            else:
                s.select_by_value(str(valor))
        except Exception:
            # campo oculto (seção recolhida): define via JavaScript e dispara 'change'
            ok = self.d.execute_script("""
                const s = arguments[0], v = arguments[1], t = arguments[2];
                const o = [...s.options].find(o => t !== null ? o.text.trim() === t : o.value === v);
                if (!o) return false;
                s.value = o.value;
                s.dispatchEvent(new Event('change', {bubbles:true}));
                return true;""", el, None if valor is None else str(valor), texto)
            if not ok:
                raise MoodleError(f"Opção '{texto if texto is not None else valor}' não existe em {css}")

    def marcar(self, css, marcado=True):
        el = self.um(css)
        if el.is_selected() != marcado:
            self.d.execute_script("arguments[0].click();", el)

    def js(self, script, *args):
        return self.d.execute_script(script, *args)

    def texto_pagina(self):
        try:
            return self.um("body").text
        except Exception:
            return ""

    @property
    def sesskey(self):
        return self.js("return (window.M && M.cfg) ? M.cfg.sesskey : null;")

    def expandir_formulario(self):
        """Abre todas as seções recolhidas de um formulário Moodle."""
        self.js("""
            document.querySelectorAll('a.moreless-toggler, .collapsible-actions a.collapseexpand').forEach(a=>{
              if (a.textContent.match(/Expandir tudo|Expand all/i)) a.click();});
            document.querySelectorAll('fieldset.collapsible.collapsed, fieldset.collapsed').forEach(f=>f.classList.remove('collapsed'));
            document.querySelectorAll('fieldset .fcontainer.collapse').forEach(f=>f.classList.add('show'));
        """)
        time.sleep(0.4)

    def editor(self, campo_id, html):
        """Define o conteúdo de um editor (TinyMCE/Atto/textarea) pelo id da textarea."""
        self.js("""
            const id = arguments[0], html = arguments[1];
            if (window.tinyMCE && tinyMCE.get(id)) { tinyMCE.get(id).setContent(html); tinyMCE.get(id).save(); }
            const ta = document.getElementById(id); if (ta) { ta.value = html; ta.dispatchEvent(new Event('change')); }
            const atto = document.getElementById(id + 'editable'); if (atto) atto.innerHTML = html;
        """, campo_id, html)

    # ------------------------------------------------------------ erros / prints
    def print(self, nome):
        nome = re.sub(r"[^\w\-]+", "_", nome)[:90]
        caminho = os.path.join(self.prints_dir, f"{time.strftime('%H%M%S')}_{nome}.png")
        try:
            # print da página inteira (Chrome DevTools)
            m = self.d.execute_cdp_cmd("Page.getLayoutMetrics", {})
            h = min(int(m["cssContentSize"]["height"]), 8000)
            w = int(m["cssContentSize"]["width"])
            self.d.execute_cdp_cmd("Emulation.setDeviceMetricsOverride",
                                   {"width": max(w, 1440), "height": h, "deviceScaleFactor": 1, "mobile": False})
            self.d.save_screenshot(caminho)
            self.d.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})
        except Exception:
            try:
                self.d.save_screenshot(caminho)
            except Exception:
                return None
        return caminho

    def erros_pagina(self):
        """Erros visíveis do Moodle/PHP na página atual."""
        achados = []
        try:
            src = self.d.page_source
        except Exception:
            return achados
        for p in PADROES_ERRO:
            m = re.search(p, src)
            if m:
                trecho = src[max(0, m.start() - 80): m.end() + 160]
                trecho = re.sub(r"<[^>]+>", " ", trecho)
                achados.append(re.sub(r"\s+", " ", trecho).strip())
        for el in self.acha(".alert-danger, .errorbox, .notifyproblem, #notice.errorbox"):
            try:
                if el.is_displayed() and el.text.strip():
                    achados.append("Alerta: " + el.text.strip()[:300])
            except StaleElementReferenceException:
                pass
        return list(dict.fromkeys(achados))

    def erros_js(self):
        try:
            logs = self.d.get_log("browser")
        except Exception:
            return []
        ignorar = ("favicon", "net::ERR_BLOCKED_BY_CLIENT", "youtube", "doubleclick", "google-analytics",
                   "googletagmanager", "hotjar", "clarity", "chatwoot", "tawk")
        return [l["message"][:300] for l in logs
                if l["level"] == "SEVERE" and not any(i in l["message"].lower() for i in ignorar)]

    # ------------------------------------------------------------ sessão / cookies
    def cookies_requests(self):
        import requests
        s = requests.Session()
        for c in self.d.get_cookies():
            s.cookies.set(c["name"], c["value"], domain=c.get("domain"))
        s.headers["User-Agent"] = self.js("return navigator.userAgent")
        return s

    def fechar(self):
        try:
            self.d.quit()
        except Exception:
            pass


class Moodle(Browser):
    """Ações de usuário no Moodle (testado em Moodle 4.x/5.x, tema Moove/Boost)."""

    def login(self, usuario, senha):
        self.get("login/index.php")
        self.fechar_avisos()
        self.preencher("#username", usuario)
        self.preencher("#password", senha)
        self.clicar("#loginbtn")
        if "login/index.php" in self.d.current_url:
            msg = " ".join(e.text for e in self.acha(".alert-danger, .loginerrors"))
            raise MoodleError(f"Falha no login: {msg or 'motivo desconhecido'}")
        self.fechar_avisos()
        return True

    def logout(self):
        sk = self.sesskey
        if sk:
            self.get(f"login/logout.php?sesskey={sk}")
            botoes = self.acha("form[action*='logout'] button[type=submit], .modal button.btn-primary")
            if botoes:
                self.clicar(botoes[0])

    def fechar_avisos(self):
        """Fecha banners de cookies, tours e modais que atrapalham cliques."""
        self.js("""
            document.querySelectorAll('[data-role="end"], .tour-skip, button[data-action="hide"]').forEach(b=>{try{b.click()}catch(e){}});
            document.querySelectorAll('#cookie-consent button, .eupopup-button_1, .cookie-notice button').forEach(b=>{try{b.click()}catch(e){}});
        """)

    def versao(self):
        """Tenta descobrir a versão do Moodle por pistas públicas."""
        info = {}
        try:
            import requests
            r = requests.get(self.base + "/lib/upgrade.txt", timeout=15)
            info["upgrade.txt"] = r.status_code
        except Exception:
            pass
        info["tema"] = self.js("return (window.M && M.cfg) ? M.cfg.theme : null;")
        return info

    # ---------- papel
    def papel_trocado(self, course_id):
        """True se o usuário está com o papel trocado ('Retornar ao meu papel normal' no menu)."""
        if f"course/view.php?id={course_id}" not in self.d.current_url or not self.sesskey:
            self.get(f"course/view.php?id={course_id}")
        return self.existe("a[href*='switchrole=0']")

    def mudar_papel(self, course_id, nome_papel):
        if self.papel_trocado(course_id):
            return  # já está no papel de estudante
        self.get(f"course/switchrole.php?id={course_id}&switchrole=-1&returnurl=/course/view.php?id={course_id}")
        botoes = self.xp(f"//form//button[normalize-space()={json.dumps(nome_papel)}] | "
                         f"//form//input[@type='submit' and @value={json.dumps(nome_papel)}]")
        if not botoes:
            raise MoodleError(f"Papel '{nome_papel}' não disponível em Mudar papel")
        self.clicar(botoes[0])

    def voltar_papel_normal(self, course_id):
        if not self.papel_trocado(course_id):
            return
        link = self.acha("a[href*='switchrole=0']")
        self.get(link[0].get_attribute("href"))
        if self.papel_trocado(course_id):
            raise MoodleError("Não foi possível voltar ao papel normal")

    def edicao(self, ligar=True):
        """Liga/desliga o modo de edição pelo botão do cabeçalho."""
        chk = self.acha("input[name='setmode'], .editmode-switch-form input[type=checkbox]")
        if chk:
            if chk[0].is_selected() != ligar:
                self.clicar(chk[0])
                self.aguardar_carregar(1)
            return True
        return False

    # ---------- curso
    def atividades_curso(self, course_id):
        """Lista as atividades da página do curso: [{secao, tipo, cmid, nome, url}]"""
        self.get(f"course/view.php?id={course_id}")
        res = self._atividades_pagina()
        # layout "uma seção por página": percorre cada seção
        secoes = self.js("return [...new Set([...document.querySelectorAll('li.section[data-id], li.course-section[data-id]')]"
                         ".map(s=>s.getAttribute('data-id')))]")
        n_sec_com_ativ = len({a["secnum"] for a in res})
        if secoes and n_sec_com_ativ < len(secoes) and self.existe("a[href*='section.php']"):
            vistos = {a["cmid"] for a in res}
            for sid in secoes:
                self.get(f"course/section.php?id={sid}")
                for a in self._atividades_pagina():
                    if a["cmid"] not in vistos:
                        vistos.add(a["cmid"])
                        res.append(a)
        return res

    def _atividades_pagina(self):
        return self.js("""
            const out = [];
            document.querySelectorAll('li.section, li.course-section').forEach(s => {
              const sn = s.getAttribute('data-sectionname') || (s.querySelector('.sectionname, h3')||{}).textContent || '';
              const snum = s.getAttribute('data-number') || (s.id||'').replace('section-','');
              s.querySelectorAll('li.activity').forEach(a => {
                const m = (a.className.match(/modtype_(\\w+)/)||[])[1];
                const link = a.querySelector('a.aalink, .activityname a, a[href*="/mod/"]');
                const nome = (a.querySelector('.instancename, .activityname')||a).textContent.replace(/\\s+/g,' ').trim();
                out.push({secao: sn.trim(), secnum: snum, tipo: m, cmid: (a.id||'').replace('module-',''),
                          nome: nome, url: link ? link.href : null,
                          restrito: !!a.querySelector('.availabilityinfo, [data-region="availabilityinfo"]'),
                          texto: a.innerText.slice(0, 500), html: a.innerHTML.slice(0, 6000)});
              });
            });
            return out;""")

    def secoes_curso(self, course_id):
        self.get(f"course/view.php?id={course_id}")
        return self.js("""
            return [...document.querySelectorAll('li.section, li.course-section')].map(s => ({
              id: s.getAttribute('data-id'), numero: s.getAttribute('data-number') || (s.id||'').replace('section-',''),
              nome: (s.getAttribute('data-sectionname') || (s.querySelector('.sectionname, h3')||{}).textContent || '').trim(),
              atividades: s.querySelectorAll('li.activity').length,
              resumo: (s.querySelector('.summarytext, .section_summary, [data-for="sectioninfo"]')||{}).innerText || ''
            }));""")

    # ---------- formulários de módulo
    def abrir_form_modulo(self, course_id, modulo, secao):
        self.get(f"course/modedit.php?add={modulo}&type=&course={course_id}&section={secao}&return=0&sr=0",
                 esperar="#id_name, form.mform")
        self.expandir_formulario()

    def salvar_form(self, voltar_curso=True):
        btn = "#id_submitbutton2" if voltar_curso and self.existe("#id_submitbutton2") else "#id_submitbutton"
        self.clicar(btn)
        self.aguardar_carregar(0.8)
        erros = [e.text for e in self.acha(".invalid-feedback, .error") if e.is_displayed() and e.text.strip()]
        if erros and self.existe("form.mform #id_submitbutton"):
            raise MoodleError("Erro de validação do formulário: " + " | ".join(erros))

    def upload_filemanager(self, caminho, container_css=None):
        """Envia arquivo por um filemanager/filepicker (repositório 'Enviar um arquivo')."""
        caminho = os.path.abspath(caminho)
        base = container_css or ""
        botao = self.acha(f"{base} .fp-btn-add a, {base} .fp-btn-add button, {base} input.fp-btn-choose, "
                          f"{base} button.fp-btn-choose, {base} .fp-btn-choose")
        if not botao:
            raise MoodleError("Botão 'Adicionar arquivo' não encontrado")
        self.clicar(botao[0])
        dlg = self.espera(".file-picker.fp-generallayout, .moodle-dialogue-base .file-picker", visivel=True)
        # escolhe o repositório de upload
        for r in self.acha(".fp-repo-area .fp-repo a, .fp-repo-area .nav-link"):
            if re.search(r"Enviar um arquivo|Upload a file", r.text, re.I):
                self.clicar(r)
                break
        inp = self.espera(".fp-upload-form input[type=file]", visivel=False)
        inp.send_keys(caminho)
        self.clicar(self.espera(".fp-upload-btn", visivel=True))
        # sobrescrever se já existir
        time.sleep(1.5)
        for b in self.acha(".fp-dlg-butoverwrite"):
            if b.is_displayed():
                self.clicar(b)
        WebDriverWait(self.d, 60).until(lambda d: not any(
            e.is_displayed() for e in d.find_elements(By.CSS_SELECTOR, ".file-picker.fp-generallayout")))
        time.sleep(0.8)
