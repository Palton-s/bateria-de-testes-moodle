"""
Testes automatizados do Moodle (roteiro de testes + extras), simulando professor e estudante.

Uso:
    python executar.py                      # roda em todos os ambientes ativos do config.json
    python executar.py --ambiente novo      # só um ambiente
    python executar.py --visivel            # mostra o navegador
    python executar.py --somente R06,R07    # só alguns itens
    python executar.py --sem-formatos       # pula o teste de troca de formatos (mais rápido)
    python executar.py --comparar resultados/<pasta_antigo> resultados/<pasta_novo>

Saída: resultados/<data_hora>/<ambiente>/  ->  relatorio.html, ERROS.txt, resultados.json, prints/
"""
import argparse
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from moodle_tester import arquivos  # noqa: E402
from moodle_tester.core import Moodle, MoodleError  # noqa: E402
from moodle_tester.preparacao import Preparador  # noqa: E402
from moodle_tester.relatorio import relatorio_ambiente, relatorio_comparativo, relatorio_erros  # noqa: E402
from moodle_tester.resultado import Registro, FALHA  # noqa: E402
from moodle_tester.testes import Suite  # noqa: E402


def credenciais_arquivo(nome="dados de acesso.txt"):
    """Lê 'dados de acesso.txt'. Formato:
        url: ...
        usuario: ...        (professor)
        senha: ...
        aluno:              (seção opcional)
        usuário: ...
        senha: ...
    Retorna {"url":..., "professor": {...}, "aluno": {...}}."""
    import unicodedata
    caminho = os.path.join(RAIZ, nome)
    dados = {"professor": {}, "aluno": {}}
    secao = "professor"
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8-sig") as f:
            for linha in f:
                if ":" not in linha:
                    continue
                k, v = linha.split(":", 1)
                k = unicodedata.normalize("NFKD", k.strip().lower()).encode("ascii", "ignore").decode()
                v = v.strip()
                if k == "url":
                    dados["url"] = v
                elif k in ("aluno", "estudante", "professor") and not v:
                    secao = "aluno" if k in ("aluno", "estudante") else "professor"
                elif k in ("aluno_usuario", "aluno_senha"):
                    dados["aluno"][k.split("_")[1]] = v
                elif k in ("usuario", "login", "senha"):
                    dados[secao]["usuario" if k != "senha" else "senha"] = v
    return dados


def executar_ambiente(nome, cfg, op, saida, somente=None):
    out = os.path.join(saida, nome)
    os.makedirs(out, exist_ok=True)
    reg = Registro(nome, out)
    reg.meta.update({"url": cfg["url"], "curso_id": cfg["curso_id"], "data": time.strftime("%d/%m/%Y %H:%M")})
    arq = arquivos.gerar_todos(os.path.join(RAIZ, "arquivos_teste"))

    arqcred = credenciais_arquivo(cfg.get("arquivo_credenciais", "dados de acesso.txt"))
    prof_cfg = cfg.get("professor", {})
    if not prof_cfg.get("usuario"):
        prof_cfg = arqcred["professor"]
    aluno_cfg = cfg.get("aluno", {}) or {}
    if not aluno_cfg.get("usuario"):
        aluno_cfg = arqcred["aluno"]
    modo = "conta" if aluno_cfg.get("usuario") else "papel"
    reg.meta["modo_aluno"] = "conta de estudante" if modo == "conta" else f"Mudar papel para '{op.get('papel_estudante')}'"

    headless = not op.get("navegador_visivel", False)
    prof = Moodle(cfg["url"], out, headless=headless, nome="professor")
    aluno = None
    navs = [prof]
    try:
        with reg.teste("X01", "Login do professor", prof, "Professor", critico=True) as t:
            dt = prof.get("login/index.php")
            t.ok(f"Página de login abriu ({dt:.1f}s)")
            t0 = time.time()
            prof.login(prof_cfg["usuario"], prof_cfg["senha"])
            t.ok(f"Login realizado ({time.time() - t0:.1f}s)")
            v = prof.versao()
            reg.meta["tema"] = v.get("tema")
            t.info(f"Tema: {v.get('tema')}")
            t.verificar_pagina()
        if modo == "conta":
            aluno = Moodle(cfg["url"], out, headless=headless, nome="aluno")
            navs.append(aluno)
            with reg.teste("X01", "Login do estudante", aluno, "Estudante", critico=True) as t:
                aluno.login(aluno_cfg["usuario"], aluno_cfg["senha"])
                t.ok("Login do estudante realizado")
        else:
            aluno = prof

        # ---------------- preparação do conteúdo pelo professor
        prep = Preparador(prof, reg, cfg["curso_id"], arq, op.get("prefixo", "[AUTO]"))
        with reg.teste("X00", "Configurar curso (conclusão de atividades, notas visíveis)", prof, "Professor") as t:
            prep.configurar_curso(t)
        with reg.teste("X00", "Organizar seções do curso", prof, "Professor", critico=True) as t:
            prep.secoes(t)
        with reg.teste("X00", "Criar conteúdo do roteiro (rótulos, páginas, arquivos, links, tarefa, questionário)",
                       prof, "Professor", critico=True) as t:
            prep.criar_tudo(t)
            t.foto()
        with reg.teste("R07", "Adicionar questões ao questionário (professor)", prof, "Professor") as t:
            prep.questoes_quiz(t)
            t.verificar_pagina()

        suite = Suite(reg, prof, aluno, modo, cfg["curso_id"], prep.cm, arq, op, prep.secids)
        suite.resetar_conclusao = prep.resetar_conclusao
        etapas = [
            ("X01", suite.x01_acesso),
            ("R01", suite.r01_formato_navegacao),
            ("R05", suite.r05_rotulos),
            ("R02", suite.r02_plano_ensino),
            ("R03", suite.r03_arquivos),
            ("R04", suite.r04_links),
            ("R11", suite.r11_restricoes),
            ("R06", suite.r06_tarefa),
            ("R07", suite.r07_quiz),
            ("R10", suite.r10_forum_avisos),
            ("X02", suite.x02_interacao),
            ("R08", suite.r08_livro_notas),
            ("R09", suite.r09_categorias),
            ("X03", suite.x03_calendario),
            ("X04", suite.x04_responsivo),
        ]
        for cod, fn in etapas:
            if somente and cod not in somente:
                continue
            try:
                fn()
            except Exception as e:  # falha inesperada fora de um passo: registra e segue
                with reg.teste(cod, f"Erro inesperado na etapa {cod}", prof, "Sistema") as t:
                    t.falha(f"{type(e).__name__}: {str(e)[:200]}")
                try:
                    suite.como_professor()
                except Exception:
                    pass
        suite.x05_x06_resumo(navs)
    except MoodleError as e:
        reg.log(f"Execução interrompida: {e}")
    except Exception as e:
        reg.log(f"Execução interrompida por erro: {type(e).__name__}: {e}")
    finally:
        try:
            if modo == "papel":
                prof.voltar_papel_normal(cfg["curso_id"])
        except Exception:
            pass
        for n in navs:
            n.fechar()
        reg.salvar()
        rel = relatorio_ambiente(out)
        reg.log(f"Relatório: {rel}")
        reg.log(f"Somente erros: {relatorio_erros(out)}")
        try:
            from moodle_tester.word import word_relatorio, word_erros
            reg.log(f"Word: {word_relatorio(out)} | {word_erros(out)}")
        except Exception as e:
            reg.log(f"Não foi possível gerar os arquivos Word: {e}")
    return out


def main():
    ap = argparse.ArgumentParser(description="Testes automatizados do Moodle (professor e estudante)")
    ap.add_argument("--ambiente", help="nome do ambiente no config.json (padrão: todos os ativos)")
    ap.add_argument("--visivel", action="store_true", help="mostra o navegador durante os testes")
    ap.add_argument("--somente", help="lista de itens, ex.: R06,R07,X02")
    ap.add_argument("--sem-formatos", action="store_true", help="não testa a troca de formatos de curso")
    ap.add_argument("--sem-alteracoes", action="store_true", help="não publica/envia nada (apenas leitura)")
    ap.add_argument("--comparar", nargs="+", metavar="PASTA", help="gera comparação entre pastas de resultados")
    ap.add_argument("--config", default=os.path.join(RAIZ, "config.json"))
    args = ap.parse_args()

    if args.comparar:
        pastas = {os.path.basename(p.rstrip("/\\")): p for p in args.comparar}
        destino = os.path.join(os.path.dirname(os.path.abspath(args.comparar[-1])), "comparacao.html")
        print("Comparação:", relatorio_comparativo(pastas, destino))
        return

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    op = cfg.get("opcoes", {})
    if args.visivel:
        op["navegador_visivel"] = True
    if args.sem_formatos:
        op["testar_todos_formatos"] = False
    if args.sem_alteracoes:
        op["permitir_alteracoes"] = False
    somente = set(x.strip().upper() for x in args.somente.split(",")) if args.somente else None

    ambientes = {k: v for k, v in cfg["ambientes"].items()
                 if (args.ambiente == k) or (not args.ambiente and v.get("ativo"))}
    if not ambientes:
        sys.exit("Nenhum ambiente ativo/selecionado no config.json")
    saida = os.path.join(RAIZ, "resultados", time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(saida, exist_ok=True)
    pastas = {}
    for nome, c in ambientes.items():
        if not c.get("curso_id"):
            print(f"[{nome}] curso_id não configurado - pulando")
            continue
        pastas[nome] = executar_ambiente(nome, c, op, saida, somente)
    if len(pastas) > 1:
        print("Comparação:", relatorio_comparativo(pastas, os.path.join(saida, "comparacao.html")))
    print("\nResultados em:", saida)


if __name__ == "__main__":
    main()
