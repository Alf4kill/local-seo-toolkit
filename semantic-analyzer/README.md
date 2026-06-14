# Semantic Analyzer

Ferramenta **local** que agrupa páginas de um site por **significado** (embeddings)
para revelar conteúdo duplicado / de mesma intenção — **doorway pages** e
**canibalização por conteúdo**. 100% local, sem cota nem custo de API.

Complementa o `gsc-monitor`: enquanto o GSC vê canibalização só pelas *queries*
que já ranqueiam, aqui comparamos o *conteúdo* de **todas** as páginas — pegando
duplicatas que ainda não têm tráfego.

## Por que separado do gsc-monitor
Dependências pesadas de ML (`sentence-transformers` + `torch`) ficam isoladas; o
núcleo de clustering não precisa do GSC nem de nenhum módulo do gsc-monitor. Os
dois cooperam por **arquivos** (ex.: cruzar clusters com posições do GSC), não por
import.

## Como funciona
1. **Embeddings** — cada página vira um vetor numa "mapa de significado" (modelo
   multilíngue local, roda em CPU).
2. **Similaridade do cosseno** — mede quão próximas duas páginas estão em sentido.
3. **Clustering por limiar** — agrupa páginas com similaridade ≥ `--threshold`
   (componentes conexos). Cada grupo de 2+ páginas = candidatas a consolidação;
   a página mais central é sugerida como **canônica**.

## Setup
```powershell
pip install -r requirements.txt
```
(O núcleo + testes rodam só com `numpy`; `sentence-transformers` é necessário só
para o modo semântico de verdade.)

## Uso

### Interface gráfica

```powershell
py app.py
```

Mesma janela integrada do gsc-monitor (terminal com output em tempo real,
botões "Abrir pasta" e "Abrir relatório"). A GUI chama exatamente o pipeline
do CLI (`analisar.run_analysis`) — sem lógica duplicada: tudo que o CLI faz, a
janela faz, incluindo cruzamento GSC, julgamento LLM, diferenciação e grafo de
links.

### CLI

> 📋 Referência completa das opções + exemplos prontos para copiar: **[COMANDOS.md](COMANDOS.md)**.

```powershell
# Backup de um site primeWeb (lê include/parametros.php → $blog + $palavras_chave)
py analisar.py --primeweb "E:/projetos/backup/exemplo" --html clusters.html

# Qualquer pasta de .php/.html, limiar mais estrito
py analisar.py --folder "E:/.../site" --threshold 0.82

# Escolher a página a MANTER por performance real (cruza com o gsc-monitor)
py analisar.py --primeweb "..." --gsc "E:/projetos/local-seo-toolkit/gsc-monitor/relatorios/www.exemplo.com" --html plano.html

# Julgar os grupos com um LLM LOCAL (LM Studio/Ollama na GPU — recomendado)
py analisar.py --primeweb "..." --gsc "..." --llm --llm-model qwen2.5:7b-instruct
# ...ou sem servidor, via CPU (modelo pequeno, lento — só p/ testar):
py analisar.py --primeweb "..." --llm --llm-backend transformers

# Sem sentence-transformers (resultado só LÉXICO, não semântico)
py analisar.py --primeweb "..." --backend tfidf
```

## Camada LLM (opcional, local)

`--llm` julga os maiores grupos: **spun** (mesmo texto reescrito) / **raso** / **ok**,
sugere a base p/ consolidar e lista lacunas. Backends:
- `http` (padrão): fala com **Ollama** (`ollama serve`, porta 11434) ou **LM Studio**
  (Local Server, porta 1234) — rodam o modelo na **GPU** (RX 6750XT via Vulkan).
  Ajuste `--llm-url` / `--llm-model`.
- `transformers`: roda um modelo pequeno em **CPU**, sem servidor (lento; só p/ testar).

Estratégia HYBRID: clustering acha os grupos (barato); o LLM julga só os sinalizados.

**`--differentiate`** (alternativa ao 301): quando não dá p/ apagar/redirecionar páginas
(ex.: contrato paga por nº de artigos), gera um plano de **diferenciação** — uma
intenção/keyword/título distintos por página (uma vira CABEÇA/hub, as outras spokes)
p/ pararem de canibalizar **sem remover nenhuma**. Veja exemplos em [COMANDOS.md](COMANDOS.md).

**`--linkgraph`** (grafo de links internos, sem LLM): lê o markup das páginas e monta o
grafo de links. Acha **páginas órfãs** (nenhum artigo as linka), **money-pages
sub-linkadas** (tráfego real no GSC + poucos links de entrada), **canibalização de âncora**
(mesmo texto-âncora apontando p/ páginas diferentes) e o **plano de links hub→spoke** por
grupo — que é o backbone que o `--differentiate` precisa para funcionar. Em backup/pasta
vê só os links **estáticos do corpo** (o menu do primeWeb é `include` PHP, não entra); para
o grafo completo, rode com `--urls` no site no ar.

### Ollama na GPU (passo a passo — testado na RX 6750 XT)

```powershell
winget install --id Ollama.Ollama        # instala o Ollama
.\setup-ollama.ps1                        # habilita GPU (Vulkan) + baixa qwen2.5:7b-instruct
ollama ps                                 # deve mostrar "100% GPU"
```

Depois é só rodar com `--llm` (backend http é o padrão, aponta para o Ollama):

```powershell
py analisar.py --primeweb "..." --gsc "..." --llm --llm-model qwen2.5:7b-instruct --html plano.html
```

**⚠ GPU AMD no Windows:** a 6750 XT (gfx1031) **não** é suportada pelo ROCm do
Ollama — sem ajuste ele roda em CPU. A solução é **Vulkan**: a variável de
ambiente **`OLLAMA_VULKAN=1`** (que o `setup-ollama.ps1` persiste) faz o Ollama
enxergar a placa (12 GiB) e rodar 100% na GPU. Modelos recomendados p/ 12 GB:
`qwen2.5:7b-instruct` (rápido) ou `qwen2.5:14b-instruct` (Q4, melhor, ~9 GB).

`--threshold` (0..1): maior = grupos mais estritos (só quase-idênticas). Comece em
0.80 e ajuste. Sites de tema único (ex.: uma raça de cão) podem precisar de 0.83–0.88.

## Testes
```powershell
py -m pytest
```

## Estrutura
```
analisar.py          CLI
core/
  loaders.py         obtém textos (pasta / primeweb / urls)
  embedder.py        sentence-transformers (lazy) + TF-IDF + cache (.cache/, --no-cache)
  clusterer.py       núcleo puro (numpy): cosseno + clustering (threshold/agglomerative)
  gsc_link.py        cruza clusters com {data}_posicao.json do gsc-monitor
  llm.py             cliente LLM local (Ollama/LM Studio http + transformers) + parse JSON
  hybrid.py          julga os grupos (spun/raso/ok) + modo --differentiate (cabeça/spokes)
  dedup.py           dedup de keyword entre grupos (puro stdlib) — colisões cross-cluster
  linkgraph.py       grafo de links internos: contextual vs índice/widget, money-pages, plano hub→spoke
  report.py          relatórios console + HTML
relatorios/<site>/   relatórios gerados, organizados por site/data (estilo gsc-monitor):
                     AAAA-MM-DD_<tipo>.html  (clusters/consolidacao/links/diferenciacao/plano-completo)
tests/               81 testes (núcleo numpy + LLM/hybrid/dedup/linkgraph sem servidor/ML)
```
