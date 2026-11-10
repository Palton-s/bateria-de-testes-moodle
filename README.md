# Bateria de testes do Moodle

Este programa testa um curso no Moodle de forma automática. Ele abre o navegador e repete o que um
professor e um estudante fariam no curso, seguindo o [roteiro de testes](roteiro%20de%20testes.txt).
No fim, gera relatórios com o resultado de cada verificação, com prints das telas.

O programa serve para validar um ambiente Moodle, por exemplo depois de uma migração ou atualização.
Também permite comparar dois ambientes (um antigo e um novo) lado a lado.

## Como funciona

1. **Preparação.** O professor entra no curso de teste e cria o conteúdo que o roteiro pede: seções,
   rótulos, páginas, arquivos PDF e PPTX, links, tarefa e questionário com questões. O nome de cada
   item criado começa com um prefixo (padrão `[AUTO]`). Se o item já existir, o programa usa o
   existente e não cria outro. Os arquivos usados nos envios são gerados na pasta `arquivos_teste/`.
2. **Testes.** O programa percorre o curso como professor e como estudante. Para agir como estudante,
   ele usa uma conta de estudante, se você informar uma. Sem essa conta, ele usa "Mudar papel para
   Estudante" com o login do professor.
3. **Relatórios.** Cada verificação recebe um status: `OK`, `FALHA`, `AVISO`,
   `VERIFICAR MANUALMENTE` ou `NÃO SE APLICA`.

### O que é testado

| Código | Item |
|---|---|
| R01 | Formato e navegação (inclusive troca entre todos os formatos de curso) |
| R02 | Plano de ensino / apresentação (inclusive substituição do arquivo) |
| R03 | Arquivos PDF e slides (download e visualização) |
| R04 | Links externos |
| R05 | Rótulos e organização |
| R06 | Tarefa: instruções, prazo, limite de tamanho e envio de teste pelo estudante |
| R07 | Questionário: tentativa completa, tempo, número de tentativas e correção automática |
| R08 | Configuração do livro de notas (soma total 10 ou 100) |
| R09 | Categorias e médias (agregação) |
| R10 | Fórum de avisos (publicação de mensagem) |
| R11 | Restrições de acesso e conclusão (bloqueio e desbloqueio) |
| X01 | Extra: acesso, painel e "Meus cursos" |
| X02 | Extra: interação entre professor e estudante |
| X03 | Extra: calendário e prazos |
| X04 | Extra: responsividade (celular e tablet) |
| X05 | Extra: erros de PHP e JavaScript nas páginas |
| X06 | Extra: desempenho (tempo de carregamento) |
| X07 | Extra: validações de envio (tamanho e tipo de arquivo) |

> **Atenção:** o programa altera o curso. Ele cria conteúdo, troca o formato do curso, envia arquivos
> e publica no fórum. Use sempre um **curso de teste**. Para rodar sem alterar nada, use
> `--sem-alteracoes`.

## Requisitos

- Python 3.11 ou mais recente
- Google Chrome instalado (o Selenium baixa o driver automaticamente)
- Bibliotecas Python:

```bash
pip install selenium requests pillow python-docx
```

## Configuração

Os arquivos com dados reais ficam fora do Git. Crie-os a partir dos exemplos:

```bash
cp config.exemplo.json config.json
cp "dados de acesso.exemplo.txt" "dados de acesso.txt"
```

### `config.json`

Cada entrada em `ambientes` é um Moodle a ser testado:

| Campo | Descrição |
|---|---|
| `ativo` | `true` para incluir o ambiente na execução padrão |
| `url` | Endereço do Moodle |
| `curso_id` | ID do curso de teste (o número em `course/view.php?id=...`). Ambientes com `0` são pulados |
| `arquivo_credenciais` | Arquivo com o login do professor e do estudante |
| `professor` / `aluno` | Login direto. Se ficar vazio, o programa lê o login do arquivo de credenciais |

Em `opcoes`, você ajusta o comportamento geral:

| Opção | Para que serve |
|---|---|
| `navegador_visivel` | Mostra o navegador durante a execução |
| `prefixo` | Texto no início do nome dos itens criados (padrão `[AUTO]`) |
| `permitir_alteracoes` | Permite que o programa crie conteúdo, envie arquivos e publique |
| `testar_todos_formatos` | Testa a troca entre os formatos de curso |
| `formatos_ignorar` | Formatos que não entram nesse teste |
| `papel_estudante` | Nome do papel usado no "Mudar papel" |
| `nota_total_esperada` | Totais aceitos para o livro de notas (por exemplo `[10, 100]`) |
| `agregacao_esperada` | Tipo de agregação esperado nas categorias de notas |
| `tempo_lento_segundos` | Tempo de carregamento a partir do qual uma página conta como lenta |
| `max_links_externos` | Número máximo de links externos verificados |

### Arquivo de credenciais (`dados de acesso.txt`)

```
url: https://seu-moodle.exemplo.com.br/
usuario: USUARIO_PROFESSOR
senha: SENHA_PROFESSOR

aluno:
usuário: USUARIO_ESTUDANTE
senha: SENHA_ESTUDANTE
```

A seção `aluno:` é opcional. Sem ela, os testes de estudante usam "Mudar papel". Cada ambiente pode
ter seu próprio arquivo, por exemplo `dados de acesso 2.txt`.

## Uso

```bash
python executar.py                      # todos os ambientes ativos
python executar.py --ambiente novo_aprender3   # só um ambiente
python executar.py --visivel            # mostra o navegador
python executar.py --somente R06,R07    # só alguns itens
python executar.py --sem-formatos       # pula a troca de formatos (mais rápido)
python executar.py --sem-alteracoes     # não publica nem envia nada (só leitura)
python executar.py --config outro.json  # usa outro arquivo de configuração
python executar.py --comparar resultados/<pasta_antigo> resultados/<pasta_novo>
```

## Resultados

Cada execução cria a pasta `resultados/<data_hora>/<ambiente>/` com:

- `relatorio.html`: relatório completo, com status, detalhes e prints de cada item
- relatório só de erros, em HTML e `ERROS.txt`
- versões Word (`.docx`) dos dois relatórios
- `resultados.json`: dados brutos, usados também na comparação
- `log_execucao.txt`: log da execução
- `prints/`: capturas de tela

Quando mais de um ambiente roda na mesma execução, o programa também gera `comparacao.html`. Também
dá para gerar a comparação depois, com `--comparar`.

## Estrutura do código

```
executar.py               # ponto de entrada (linha de comando)
moodle_tester/
  core.py                 # navegador Selenium, login, captura de erros e prints
  arquivos.py             # gera os arquivos de teste (PDF, PPTX, arquivo grande, tipo proibido)
  preparacao.py           # cria o conteúdo do roteiro no curso
  testes.py               # testes R01 a R11 e X01 a X07
  resultado.py            # registro dos resultados e status
  relatorio.py            # relatórios HTML e comparação
  word.py                 # relatórios em Word
roteiro de testes.txt     # roteiro manual que deu origem aos testes
```
