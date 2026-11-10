"""Registro dos resultados: cada verificação vira um item com status, detalhes e prints."""
import json
import os
import time
import traceback

OK, FALHA, AVISO, MANUAL, NA = "OK", "FALHA", "AVISO", "VERIFICAR MANUALMENTE", "NÃO SE APLICA"

# Itens do roteiro recebido + extras
ROTEIRO = {
    "R01": "Formato e Navegação",
    "R02": "Plano de Ensino / Apresentação",
    "R03": "Arquivos em PDF/Slides",
    "R04": "Links Externos",
    "R05": "Rótulos e Organização",
    "R06": "Tarefa (Envio de Arquivo/Texto)",
    "R07": "Questionário (Quiz)",
    "R08": "Configuração do Livro de Notas",
    "R09": "Categorias e Médias",
    "R10": "Fórum de Avisos",
    "R11": "Restrições de Acesso e Conclusão",
    "X01": "Extra: Acesso, Painel e Meus cursos",
    "X02": "Extra: Interação Professor ↔ Estudante",
    "X03": "Extra: Calendário e Prazos",
    "X04": "Extra: Responsividade (celular/tablet)",
    "X05": "Extra: Erros de PHP/JavaScript nas páginas",
    "X06": "Extra: Desempenho (tempo de carregamento)",
    "X07": "Extra: Validações de envio (tamanho e tipo de arquivo)",
    "X00": "Preparação do ambiente de teste",
}


class Registro:
    def __init__(self, ambiente, out_dir):
        self.ambiente = ambiente
        self.out_dir = out_dir
        self.itens = []
        self.inicio = time.time()
        self.meta = {}
        self._log = open(os.path.join(out_dir, "log_execucao.txt"), "a", encoding="utf-8")

    def log(self, msg):
        linha = f"[{time.strftime('%H:%M:%S')}] [{self.ambiente}] {msg}"
        print(linha, flush=True)
        self._log.write(linha + "\n")
        self._log.flush()

    def teste(self, codigo, titulo, navegador=None, papel="Professor", critico=False):
        return Passo(self, codigo, titulo, navegador, papel, critico)

    def salvar(self):
        dados = {"ambiente": self.ambiente, "meta": self.meta, "duracao_s": round(time.time() - self.inicio, 1),
                 "itens": self.itens}
        with open(os.path.join(self.out_dir, "resultados.json"), "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        # arquivo só com os erros (pedido: "tire prints e salve em um arquivo")
        with open(os.path.join(self.out_dir, "ERROS.txt"), "w", encoding="utf-8") as f:
            ruins = [i for i in self.itens if i["status"] in (FALHA, AVISO)]
            f.write(f"Ambiente: {self.ambiente}  |  {time.strftime('%d/%m/%Y %H:%M')}\n")
            f.write(f"Falhas: {sum(i['status'] == FALHA for i in self.itens)}  "
                    f"Avisos: {sum(i['status'] == AVISO for i in self.itens)}  "
                    f"Total de verificações: {len(self.itens)}\n\n")
            for i in ruins:
                f.write(f"[{i['status']}] {i['codigo']} - {ROTEIRO.get(i['codigo'], '')} :: {i['titulo']}"
                        f"  (papel: {i['papel']})\n")
                for d in i["detalhes"]:
                    f.write(f"    - {d}\n")
                for p in i["prints"]:
                    f.write(f"    print: {p}\n")
                if i.get("erro_tecnico"):
                    f.write("    erro técnico: " + i["erro_tecnico"].strip().splitlines()[-1][:300] + "\n")
                f.write(f"    página: {i.get('url', '')}\n\n")
        return dados


class Passo:
    """Use com `with`: exceções viram FALHA com print automático."""

    def __init__(self, reg, codigo, titulo, nav, papel, critico):
        self.reg, self.codigo, self.titulo, self.nav, self.papel, self.critico = reg, codigo, titulo, nav, papel, critico
        self.status = OK
        self.detalhes = []
        self.prints = []
        self.dados = {}
        self.erro = None

    def __enter__(self):
        self.t0 = time.time()
        self.reg.log(f"▶ {self.codigo} {self.titulo} ({self.papel})")
        if self.nav:
            try:
                self.nav.d.get_log("browser")  # limpa o log de console acumulado
            except Exception:
                pass
        return self

    # --- status
    def _piora(self, novo):
        ordem = [OK, NA, MANUAL, AVISO, FALHA]
        if ordem.index(novo) > ordem.index(self.status):
            self.status = novo

    def ok(self, msg):
        self.detalhes.append("✔ " + msg)

    def info(self, msg):
        self.detalhes.append("ℹ " + msg)

    def falha(self, msg, print_=True):
        self._piora(FALHA)
        self.detalhes.append("✘ " + msg)
        if print_:
            self.foto("falha")

    def aviso(self, msg, print_=True):
        self._piora(AVISO)
        self.detalhes.append("⚠ " + msg)
        if print_:
            self.foto("aviso")

    def manual(self, msg):
        self._piora(MANUAL)
        self.detalhes.append("👁 " + msg)

    def na(self, msg):
        self._piora(NA)
        self.detalhes.append("– " + msg)

    def checar(self, cond, msg_ok, msg_falha, nivel=FALHA):
        if cond:
            self.ok(msg_ok)
        elif nivel == AVISO:
            self.aviso(msg_falha)
        else:
            self.falha(msg_falha)
        return bool(cond)

    def foto(self, sufixo="evidencia"):
        if not self.nav:
            return None
        p = self.nav.print(f"{self.reg.ambiente}_{self.codigo}_{self.titulo}_{sufixo}")
        if p:
            self.prints.append(os.path.relpath(p, self.reg.out_dir))
        return p

    def verificar_pagina(self):
        """Procura erros PHP/Moodle e de console JS na página atual."""
        if not self.nav:
            return
        for e in self.nav.erros_pagina():
            self.falha(f"Erro exibido na página: {e[:250]}")
        js = self.nav.erros_js()
        if js:
            self.reg.meta.setdefault("erros_js", []).append({"pagina": self.nav.d.current_url, "erros": js})
            # registrado como informação; o item X05 consolida todos os erros de JavaScript como AVISO
            self.info(f"{len(js)} erro(s) de JavaScript no console: {js[0][:200]}")

    def __exit__(self, tipo, valor, tb):
        if valor is not None:
            self.erro = "".join(traceback.format_exception(tipo, valor, tb))
            self.falha(f"Erro durante o teste: {type(valor).__name__}: {str(valor).splitlines()[0][:250] if str(valor) else ''}")
        url = ""
        if self.nav:
            try:
                url = self.nav.d.current_url
            except Exception:
                pass
        item = {"codigo": self.codigo, "titulo": self.titulo, "papel": self.papel, "status": self.status,
                "detalhes": self.detalhes, "prints": self.prints, "dados": self.dados,
                "duracao_s": round(time.time() - self.t0, 1), "url": url, "erro_tecnico": self.erro}
        self.reg.itens.append(item)
        self.reg.log(f"   {self.status}  " + (" | ".join(self.detalhes)[:400]))
        self.reg.salvar()
        if self.critico and self.status == FALHA:
            return False  # propaga a exceção (interrompe a fase)
        return True  # engole a exceção: segue para o próximo teste
