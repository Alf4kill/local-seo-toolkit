# Comandos — Semantic Analyzer

Referência rápida de **todas** as opções do `analisar.py` e exemplos prontos para
copiar/colar. Para a visão geral da ferramenta, veja o [README](README.md).

> ⚠️ **Regra de ouro:** os exemplos genéricos usam caminhos reais desta máquina.
> Nunca copie um exemplo que tenha `"..."` literal — o Python vai tentar abrir uma
> pasta chamada `...` e quebrar com `FileNotFoundError: ...\include\parametros.php`.
> Troque sempre pelo caminho real (tabela abaixo).

---

## Caminhos reais nesta máquina

Para os exemplos serem copiáveis sem edição, use estes caminhos.

**Backups primeWeb** (entrada `--primeweb`, contêm `include/parametros.php`):

| Site | Caminho |
|---|---|
| exemplo | `E:\projetos\backup\exemplo` |
| exemplo2 | `E:\projetos\backup\exemplo2.com.br` |

**Relatórios GSC** (entrada `--gsc`, gerados pelo `gsc-monitor`):

| Site | Pasta (`--gsc` pega o snapshot mais novo sozinho) |
|---|---|
| exemplo | `E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com.br` |

> Para o cruzamento `--gsc` valer a pena, o site precisa ter **backup _e_** relatório
> GSC (os slugs do conteúdo casam com as URLs do GSC). Hoje o caso completo é o
> **exemplo** — por isso ele aparece em todos os exemplos abaixo.

---

## Início rápido

```powershell
# 1) Só achar os grupos de páginas duplicadas (semântico, local)
py analisar.py --primeweb "E:\projetos\backup\exemplo"

# 2) + relatório HTML
py analisar.py --primeweb "E:\projetos\backup\exemplo" --html clusters.html

# 3) Plano de consolidação completo (grupos + qual MANTER por GSC + veredito do LLM)
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --llm --site-context "Canil que vende filhotes de Cane Corso e Rottweiler" `
  --html plano.html
```

> No PowerShell o crase `` ` `` no fim da linha quebra o comando em várias linhas.
> Em uma linha só, é só remover os crases.

---

## Todas as opções

### Fonte das páginas (escolha **uma**, obrigatória)

| Opção | Valor | O que faz |
|---|---|---|
| `--primeweb` | DIR | Pasta-base de um site primeWeb; lê `include/parametros.php` (`$blog` + `$palavras_chave`). |
| `--folder` | DIR | Qualquer pasta com arquivos `.php`/`.html`. |
| `--urls` | ARQ | Arquivo `.txt` com uma URL por linha (baixa e extrai o texto). |

### Clustering

| Opção | Padrão | Valores | O que faz |
|---|---|---|---|
| `--threshold` | `0.85` | 0..1 | Similaridade mínima p/ agrupar. **Maior = grupos mais estritos.** |
| `--method` | `agglomerative` | `agglomerative`, `threshold` | `agglomerative` (sklearn, coeso, recomendado) ou `threshold` (numpy, single-linkage). |
| `--linkage` | `complete` | `complete`, `average` | Linkage do agglomerative. `complete` = todos do grupo mutuamente similares. |
| `--min-chars` | `300` | int | Ignora páginas com menos texto que isso. |

### Embeddings

| Opção | Padrão | Valores | O que faz |
|---|---|---|---|
| `--backend` | `auto` | `auto`, `st`, `tfidf` | Motor de vetores. `auto` usa sentence-transformers se instalado; `tfidf` = só léxico. |
| `--model` | (multilíngue MiniLM) | nome ST | Troca o modelo sentence-transformers. |
| `--no-cache` | (desligado) | flag | Ignora o cache em `.cache/` e recalcula os embeddings. |

### Cruzamento com GSC

| Opção | Padrão | Valor | O que faz |
|---|---|---|---|
| `--gsc` | — | PATH | Arquivo `YYYY-MM-DD_posicao.json` **ou** a pasta dele (pega o mais novo). Escolhe a página a MANTER pela performance real (cliques → impressões → posição) e ordena os grupos por impressões em disputa. |

### Camada LLM (julgamento local)

| Opção | Padrão | Valores | O que faz |
|---|---|---|---|
| `--llm` | (desligado) | flag | Liga o julgamento dos maiores grupos (`spun`/`raso`/`ok` + base + lacunas). |
| `--differentiate` | (desligado) | flag | Em vez de fundir/301, gera um plano de **DIFERENCIAÇÃO**: intenção/keyword/título distintos por página. Mantém TODOS os artigos (contract-safe). Roda também o **dedup de keyword entre grupos** (flag colisões). Pode combinar com `--llm`. |
| `--llm-backend` | `http` | `http`, `transformers` | `http` = Ollama/LM Studio (GPU). `transformers` = CPU, sem servidor (lento). |
| `--llm-url` | Ollama `localhost:11434/v1` | URL | Endpoint OpenAI-compat (LM Studio = `localhost:1234/v1`). |
| `--llm-model` | `qwen2.5:7b-instruct` | nome | Modelo do servidor (ou id HuggingFace no `transformers`). |
| `--llm-max` | `8` | int | Quantos grupos julgar (prioriza por impressões em disputa). |
| `--llm-unload` | (desligado) | flag | Ao terminar o LLM, **descarrega o modelo da memória na hora** (Ollama keep_alive=0) em vez de esperar ~5 min. Libera VRAM/RAM. No-op em LM Studio. |
| `--site-context` | — | texto | 1 linha sobre o nicho — melhora muito as lacunas. Ex.: `"Canil que vende filhotes de Cane Corso e Rottweiler"`. |

### Grafo de links internos

| Opção | Padrão | Valores | O que faz |
|---|---|---|---|
| `--linkgraph` | (desligado) | flag | Monta o grafo de **links internos** (lê o markup das páginas, sem API). Classifica cada página em 3 níveis — **com link contextual** / **só índice-widget** / **órfã de fato** — e acha **money-pages sem link contextual** (tráfego real no GSC + 0 link editorial), **canibalização de âncora** e o **plano hub→spoke por grupo** (completa o `--differentiate`). Não precisa de LLM. |

> **Template-aware (primeWeb):** além dos links de corpo, o tool entende os links que o
> template gera por **array** do `parametros.php` — o índice `blog.php`
> (`foreach $blog` → linka todos os artigos) e o widget de “relacionados”
> (`array_rand $artigos`). Eles entram como **índice/widget** (passam pouca autoridade),
> SEPARADOS dos links **contextuais** (de corpo, editoriais — os que importam). Por isso a
> métrica certa é **“sem link contextual”**, não “órfã”: uma página linkada só pelo índice
> NÃO é órfã, mas também não recebe link editorial.
>
> **Escopo:** em `--primeweb`/`--folder` lemos o `.php` FONTE (links de corpo + arrays do
> template). O menu/rodapé via `include` PHP não entram. Para o grafo **renderizado completo**
> (com a navegação), rode com `--urls` no site no ar.

### Saída

| Opção | Padrão | Valor | O que faz |
|---|---|---|---|
| `--html` | — | ARQ | Salva o relatório em HTML (inclui GSC, vereditos do LLM, plano de diferenciação e o grafo de links quando presentes). |

---

## Receitas por cenário

**Ajustar o limiar** (site de tema único costuma precisar de 0.83–0.88):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" --threshold 0.88 --html clusters.html
```

**Só o cruzamento com GSC** (sem LLM) — já dá o plano KEEP/301:
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --html plano.html
```

**Fixar uma data de GSC** (em vez do snapshot mais novo):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com\2026-06-02_posicao.json"
```

**Plano de DIFERENCIAÇÃO** (contract-safe — quando *não* dá p/ 301, porque o cliente paga por nº de artigos):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --differentiate --llm-max 5 `
  --site-context "Canil de Cane Corso e Rottweiler" --html plano_diff.html
```
Para cada página do grupo, sugere uma intenção/keyword/título distintos (uma vira **CABEÇA/hub**, as outras **spokes**) p/ pararem de competir — sem apagar nenhuma. Páginas sem ângulo distinto possível são marcadas como candidatas a `rel=canonical` (não 301). Como a diferenciação roda um grupo por vez, ela **detecta automaticamente colisões de keyword entre grupos** (seção "⚠ Colisões de keyword" no console e no HTML): a página de maior tráfego mantém a keyword, as outras precisam de uma distinta. É um RASCUNHO p/ o analista revisar; combine com `--llm` p/ ter veredito + plano juntos.

**Grafo de links internos** (órfãs + money-pages sub-linkadas + plano hub→spoke):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --linkgraph --html plano_links.html
```
Sem LLM já acha órfãs/money-pages/âncora e propõe o backbone de links (cabeça = canônica do GSC).
Combine com `--differentiate` para o plano de links usar a **cabeça/spokes** e a **keyword** como
âncora — é a sequência completa: diferenciar a intenção *e* wireá-las com links internos:
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --differentiate --linkgraph --llm-max 5 `
  --site-context "Canil de Cane Corso e Rottweiler" --html plano_full.html
```
Caso real (exemplo): **13 com link contextual, 273 só índice/widget, 0 órfãs de fato** — as
doorway pages são alcançadas pelo índice `blog.php`, mas **não recebem link editorial/contextual**
(o que de fato passa autoridade). As money-pages de maior tráfego (`preco-do-cane-corso-filhote`
11k impr, `cane-corso-preco` 5,9k impr) têm **0 link contextual de entrada** — é o que o plano
hub-and-spoke resolve.

**Hybrid completo, julgando só os 3 maiores grupos** (rápido):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --llm --llm-max 3 --site-context "Canil de Cane Corso e Rottweiler" --html plano.html
```

**LLM em CPU, sem servidor** (só p/ testar — lento, modelo pequeno):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" --llm --llm-backend transformers
```

**Apontar para o LM Studio** em vez do Ollama:
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" --llm `
  --llm-url "http://localhost:1234/v1" --llm-model "qwen2.5-7b-instruct"
```

**Sem sentence-transformers** (resultado só léxico):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" --backend tfidf
```

**Outra pasta de arquivos / lista de URLs:**
```powershell
py analisar.py --folder "E:\projetos\site-exemplo" --threshold 0.85 --html site.html
py analisar.py --urls "E:\projetos\lista_urls.txt" --html externo.html
```

**Forçar recálculo dos embeddings** (depois de mudar o conteúdo):
```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" --no-cache
```

---

## Pré-requisitos do `--llm` (GPU local)

O backend padrão (`http`) precisa de um servidor LLM no ar. Uma vez só:

```powershell
winget install --id Ollama.Ollama   # se ainda não tiver
.\setup-ollama.ps1                  # liga GPU (Vulkan) + contexto 8k + baixa qwen2.5:7b-instruct
ollama ps                           # confirme: deve mostrar 100% GPU
```

Se aparecer `[llm] Nenhum servidor LLM em ...`, o Ollama não está rodando: rode
`ollama serve` (ou abra o app da bandeja), ou use `--llm-backend transformers` (CPU).

> **GPU AMD (RX 6750 XT):** o ROCm do Ollama no Windows não enxerga essa placa →
> sem ajuste ele cai pra CPU. O `setup-ollama.ps1` resolve persistindo
> `OLLAMA_VULKAN=1`. Veja o README para detalhes.

### Qual modelo? (7B vs 14B)

Os dois cabem 100% na GPU de 12 GB (com `OLLAMA_CONTEXT_LENGTH=8192`):

| Modelo | VRAM | Quando usar |
|---|---|---|
| `qwen2.5:7b-instruct` (padrão) | ~4.7 GB | Rápido. Ótimo para clusters pequenos e coesos (ex.: variações de preço). |
| `qwen2.5:14b-instruct` | ~9 GB | Review mais fino; discrimina melhor grupos GRANDES/heterogêneos (menos "fundir tudo"). Mais lento. |

```powershell
.\setup-ollama.ps1 qwen2.5:14b-instruct    # baixa o 14B
# ...e use no analisador:
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --llm --llm-model qwen2.5:14b-instruct `
  --site-context "Canil de Cane Corso e Rottweiler" --html plano_14b.html
```

> **Por que contexto 8192 e não 16384?** Os prompts deste analisador têm ~4k tokens.
> Com 16k, o KV-cache do 14B passa de 3 GB e estoura os 12 GB → parte cai pra CPU e
> fica lento. 8192 mantém o 14B 100% na GPU sem perder nada nesta tarefa.

---

## O que cada execução gera

- **Console:** lista dos grupos (com GSC, se `--gsc`) + julgamento do LLM (se `--llm`).
- **`.cache/emb_*.npz`:** embeddings em cache (chave = modelo + conteúdo). Re-runs viram
  "cache HIT" instantâneo; muda só quando o texto muda ou com `--no-cache`. (Gitignored.)
- **HTML (sempre):** salvo organizado por site/data, no estilo do gsc-monitor:
  `relatorios/<site>/<AAAA-MM-DD>_<tipo>.html`. O `<tipo>` reflete a execução:
  `clusters`, `consolidacao` (com `--gsc`), `consolidacao-llm` (`--llm`),
  `diferenciacao` (`--differentiate`), `links` (`--linkgraph`) ou `plano-completo`
  (`--differentiate --linkgraph`). Use `--html CAMINHO` para sobrescrever com um caminho próprio.
  (A pasta `relatorios/` é gitignored — pode conter dados de cliente.)

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `FileNotFoundError: ...\include\parametros.php` | Você copiou um exemplo com `"..."` literal. Use o caminho real da tabela. |
| `Só 1 página(s) com texto suficiente` | Pasta errada, ou `--min-chars` alto demais. Confira o `--primeweb`/`--folder`. |
| Tudo caiu em **um grupo gigante** | `threshold` baixo + `--method threshold` (single-linkage encadeia). Use o padrão `agglomerative` e suba o `--threshold`. |
| `[llm] Nenhum servidor LLM em ...` | Ollama parado. Rode `ollama serve` / `setup-ollama.ps1`, ou `--llm-backend transformers`. |
| LLM rodando em **CPU** (lento) | Falta `OLLAMA_VULKAN=1`. Rode `setup-ollama.ps1` e confirme com `ollama ps`. |
| Acentos quebrados / `UnicodeEncodeError` | O `analisar.py` já força UTF-8; se rodar um script próprio, defina `PYTHONIOENCODING=utf-8`. |
| `--gsc` casou 0 URLs | Backup e GSC são de sites diferentes (slugs não batem), ou apontou para `historico_posicao.json` (use a pasta ou um `YYYY-MM-DD_posicao.json`). |

---

## Testes

```powershell
py -m unittest discover -s tests -t .
```
