"""Gera os arquivos usados nos testes (PDFs, slides, arquivo grande, tipo proibido)."""
import os
from PIL import Image, ImageDraw, ImageFont


def _fonte(tam):
    for f in ("arial.ttf", "DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, tam)
        except Exception:
            pass
    return ImageFont.load_default()


def pdf(caminho, titulo, linhas, paginas=2):
    imgs = []
    for p in range(paginas):
        im = Image.new("RGB", (1240, 1754), "white")
        d = ImageDraw.Draw(im)
        d.text((80, 80), titulo, fill="black", font=_fonte(48))
        y = 200
        for l in linhas:
            d.text((80, y), l, fill="black", font=_fonte(30))
            y += 50
        d.text((80, 1650), f"Página {p + 1} de {paginas} - arquivo gerado por teste automatizado", fill="gray",
               font=_fonte(22))
        imgs.append(im)
    imgs[0].save(caminho, save_all=True, append_images=imgs[1:], resolution=150)
    return caminho


def pptx(caminho, titulo, topicos):
    from pptx import Presentation
    pr = Presentation()
    s = pr.slides.add_slide(pr.slide_layouts[0])
    s.shapes.title.text = titulo
    s.placeholders[1].text = "Slides gerados por teste automatizado"
    for t in topicos:
        s = pr.slides.add_slide(pr.slide_layouts[1])
        s.shapes.title.text = t
        s.placeholders[1].text = f"Conteúdo de exemplo sobre {t}."
    pr.save(caminho)
    return caminho


def pdf_grande(caminho, mb=1.6):
    """PDF válido com tamanho acima do limite configurado na tarefa (1 MB)."""
    import random
    im = Image.effect_noise((1600, 1600), 120).convert("RGB")
    im.save(caminho, "PDF", resolution=72)
    if os.path.getsize(caminho) < mb * 1024 * 1024:
        with open(caminho, "ab") as f:  # comentário PDF no final (mantém o arquivo abrível)
            f.write(b"\n%" + bytes(random.getrandbits(8) % 90 + 33 for _ in range(int(mb * 1024 * 1024))))
    return caminho


def gerar_todos(pasta):
    """Gera os arquivos uma única vez (mesmo conteúdo em todas as execuções e ambientes,
    o que permite comparar o arquivo baixado com o enviado)."""
    os.makedirs(pasta, exist_ok=True)
    nomes = {"plano_v1": "plano_de_ensino_v1.pdf", "plano_v2": "plano_de_ensino_v2.pdf",
             "texto_base": "aula1_texto_base.pdf", "leitura": "aula1_leitura_complementar.pdf",
             "slides": "aula1_slides.pptx", "envio_aluno": "envio_aluno.pdf",
             "grande": "arquivo_grande_1_6MB.pdf", "proibido": "tipo_nao_permitido.txt"}
    existentes = {k: os.path.join(pasta, v) for k, v in nomes.items()}
    if all(os.path.exists(c) for c in existentes.values()):
        return existentes
    j = lambda n: os.path.join(pasta, n)
    arq = {
        "plano_v1": pdf(j("plano_de_ensino_v1.pdf"), "Plano de Ensino - versão 1", [
            "Cronograma: Aula 1 (semana 1), Aula 2 (semana 2), Avaliação (semana 3)",
            "Critérios: Tarefa 4,0 pontos + Questionário 6,0 pontos = 10,0",
            "Links: https://www.unb.br"]),
        "plano_v2": pdf(j("plano_de_ensino_v2.pdf"), "Plano de Ensino - versão 2 (ATUALIZADO)", [
            "Cronograma revisado: Aula 1 (semana 1), Aula 2 (semana 2), Avaliação (semana 4)",
            "Critérios: Tarefa 4,0 pontos + Questionário 6,0 pontos = 10,0"], paginas=3),
        "texto_base": pdf(j("aula1_texto_base.pdf"), "Aula 1 - Texto base", ["Leitura obrigatória da Aula 1."], 3),
        "leitura": pdf(j("aula1_leitura_complementar.pdf"), "Aula 1 - Leitura complementar", ["Texto opcional."]),
        "slides": pptx(j("aula1_slides.pptx"), "Aula 1 - Slides", ["Introdução", "Desenvolvimento", "Conclusão"]),
        "envio_aluno": pdf(j("envio_aluno.pdf"), "Envio de teste do estudante", ["Resposta da tarefa (teste)."], 1),
        "grande": pdf_grande(j("arquivo_grande_1_6MB.pdf")),
    }
    txt = j("tipo_nao_permitido.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("Arquivo .txt para testar bloqueio de tipo de arquivo.\n")
    arq["proibido"] = txt
    return arq
