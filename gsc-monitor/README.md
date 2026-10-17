# GSC Monitor

Ferramenta de análise do Google Search Console para múltiplos domínios.
Gera relatórios de indexação e posicionamento com Excel, dashboard HTML interativo e análises de NLP, Knowledge Graph e Google Trends.

---

## Pré-requisitos

- **Python 3.13** — [python.org/downloads](https://www.python.org/downloads/)
- **Conta Google** com acesso ao Search Console dos domínios desejados
- **Google Cloud Project** com as seguintes APIs habilitadas:
  - Google Search Console API (obrigatória)
  - Knowledge Graph Search API (opcional)
  - Cloud Natural Language API (opcional, flag `--nlp`)

---

## Setup (primeira vez)

### Windows

```powershell
# Na pasta gsc-monitor/, execute:
.\setup.ps1
```

O script cria um ambiente virtual `.venv/`, instala todas as dependências e verifica a instalação.

### Linux / Mac

```bash
chmod +x setup.sh && ./setup.sh
```

---

## Configuração de credenciais

### 1. OAuth2 — Google Search Console (obrigatório)

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. Vá em **APIs e Serviços → Credenciais**
3. Clique em **Criar credencial → ID do cliente OAuth2 → Aplicativo de desktop**
4. Baixe o arquivo JSON e renomeie para `client_secrets.json`
5. Coloque `client_secrets.json` na pasta `gsc-monitor/`

Na primeira execução o navegador abrirá para login. O token é salvo em `token.json` e reutilizado automaticamente nas execuções seguintes.

### 2. API Key — Knowledge Graph e NLP (opcional)

Crie um arquivo `google_api_key.txt` na pasta `gsc-monitor/` com a sua API key do Google Cloud, ou passe via campo na interface gráfica, ou pela flag `--api-key`.

```
AIzaSy...sua_chave_aqui
```

---

## Como executar

### Interface gráfica

```powershell
.\.venv\Scripts\python.exe app.py
```

### CLI — Posicionamento

```powershell
.\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br --excel
```

**Flags disponíveis:**

| Flag | Descrição |
|------|-----------|
| `--site` | Domínio a analisar |
| `--excel` | Gera relatório `.xlsx` |
| `--csv` | Gera relatório `.csv` |
| `--txt` | Gera relatório `.txt` legível |
| `--queries` | Analisa canibalização de keywords |
| `--trends` | Tendências de demanda — padrão: dimensão `date` do GSC (90 dias, impressões/dia do próprio site) |
| `--trends-source pytrends` | Fonte legada: índice global 0–100 do Google Trends (não-oficial, frágil) |
| `--nlp` | Analisa entidades e categorias NLP (consome cota de API) |
| `--content` | Diagnóstico de qualidade de conteúdo (sem cota) |
| `--no-cache` | Ignora cache e força dados frescos da API |
| `--api-key KEY` | API key do Google Cloud |
| `--batch ARQUIVO` | Modo lote headless: pipeline padrão para cada domínio do arquivo |
| `--batch-report` | Com `--batch`: resumo do lote em `relatorios/_batch/YYYY-MM-DD_resumo.csv` |

### CLI — Batch (vários domínios de uma vez)

```powershell
.\.venv\Scripts\python.exe posicao.py --batch sites.txt --batch-report
```

O modo batch roda o pipeline padrão de ranking (**posições + queries +
qualidade de conteúdo**, cache-aware, sem GUI) para cada domínio listado em
`sites.txt` — um por linha; linhas com `#` são comentários (modelo em
`sites.example.txt`). Para cada site, o histórico (`historico_posicao.json`)
recebe um novo snapshot e o dashboard é regenerado. Erros em um site **não
interrompem** os demais; ao final é impressa uma linha-resumo por site
(health score + grade + nº de snapshots).

Com `--batch-report`, um CSV consolidado é gravado em
`relatorios/_batch/YYYY-MM-DD_resumo.csv` com colunas: site, status, health,
grade, posição média, CTR, grupos de canibalização, contagem de vereditos de
conteúdo (ok / atenção / over-otimizado / raso) e total de snapshots.

#### Snapshots semanais automáticos (Windows Task Scheduler)

Para acumular snapshots toda semana sem rodar manualmente, crie a tarefa
agendada com uma linha (ajuste o caminho da pasta se necessário):

```powershell
schtasks /Create /TN "GSC Monitor Semanal" /SC WEEKLY /D MON /ST 08:00 /TR "cmd /c cd /d E:\projetos\projetoprst.com.br\gsc-monitor && .venv\Scripts\python.exe posicao.py --batch sites.txt --batch-report"
```

Para conferir ou remover: `schtasks /Query /TN "GSC Monitor Semanal"` e
`schtasks /Delete /TN "GSC Monitor Semanal" /F`. Requisito: `token.json` já
gerado (rode uma vez manualmente antes para autenticar no navegador — a
tarefa agendada usa o refresh silencioso do token, sem abrir janelas).

### CLI — Indexação

```powershell
.\.venv\Scripts\python.exe main.py --site www.exemplo.com.br --limit 10
```

### Plano de Poda — remoção de páginas antigas (GUI dedicada + CLI)

Premissa (convenção interna): o sitemap lista **todas** as páginas ativas —
qualquer URL que o Google conhece e que está fora do sitemap é uma página
antiga, candidata a remoção (410/404) ou a 301 quando ainda rende impressões.

```powershell
# Interface gráfica dedicada
.\.venv\Scripts\python.exe app_poda.py

# CLI — Etapa 1: gera o plano editável ({data}_poda.csv)
.\.venv\Scripts\python.exe poda.py --site www.exemplo.com.br

# (analista revisa o CSV: acao_final = 410/404/301/manter + destino_final)

# CLI — Etapa 2: compila o CSV revisado em blocos Apache/nginx
.\.venv\Scripts\python.exe poda.py --site www.exemplo.com.br --compilar
```

| Flag | Descrição |
|------|-----------|
| `--compilar [CSV]` | Etapa 2; sem valor, usa o `*_poda.csv` mais recente do domínio |
| `--min-impressoes N` | Piso de impressões para marcar `revisar` (padrão: 10) |
| `--dias N` | Janela da Search Analytics (padrão: 480 ≈ 16 meses, máx. do GSC) |
| `--importar-gsc ARQ` | Export do relatório "Páginas" do GSC (csv/txt/xlsx ou pasta) |
| `--sem-fallback-home` | Não sugere a home quando não há destino por query/slug (deixa `destino_final` em branco) |
| `--no-cache` | Ignora cache e força dados frescos da API |

> ℹ A Search Analytics só enxerga URLs que **apareceram na busca** no período
> — por isso o plano usa janela longa (16 meses) por padrão. URLs antigas com
> **zero impressões** (ex.: "Rastreada, mas não indexada" no GSC) são
> invisíveis à API: exporte o relatório de indexação na UI do Search Console
> e importe com `--importar-gsc` (ou campo "Export GSC" na GUI) para
> incluí-las no plano com origem `export-gsc`.

### CLI — Crawl Budget (logs do servidor)

Análise **100% local** do access log do servidor (Apache/Nginx) — **sem cota de
API**. Mede o comportamento real do Googlebot: frequência de crawl por URL,
páginas do sitemap **nunca rastreadas**, *money pages* com muitas impressões mas
**zero crawl**, e desperdício em URLs com parâmetro / erros 4xx.

```powershell
.\.venv\Scripts\python.exe logs.py --site www.exemplo.com.br --logs access.log
```

| Flag | Descrição |
|------|-----------|
| `--site` | Domínio analisado (obrigatório) |
| `--logs` | Um ou mais arquivos de log (aceita `.gz`) — obrigatório |
| `--format` | `combined` ou `common` (padrão: detecta automaticamente) |
| `--gsc` | Cruza com o último `*_posicao.json` salvo (money pages subcrawladas) |
| `--no-sitemap` | Não busca o sitemap (pula a lista "nunca rastreadas") |
| `--verify-googlebot` | Confirma cada IP por DNS reverso+direto (lento; elimina bot falsificado) |
| `--top N` | Quantas linhas mostrar nas tabelas "top" |

> **Honestidade analítica:** sem `--verify-googlebot`, a detecção do bot é só por
> User-Agent — que é **falsificável**. O relatório rotula isso explicitamente
> ("por UA, não verificado") em vez de afirmar certeza.
>
> **Atrás de CDN (Cloudflare etc.):** o access log normalmente registra o IP do
> *proxy*, não o do bot. Nesse caso `--verify-googlebot` marca os hits como
> **"não verificáveis"** (sem PTR) — **não** como fraude — e o relatório avisa.
> Para verificar de fato, configure o log para gravar o IP real do visitante
> (header `CF-Connecting-IP`).

#### Como exportar o access log para a sua máquina

O log fica **no servidor**; a análise roda **local**. Baixe o arquivo antes:

- **Plesk:** *Sites & Domains → (domínio) → Logs* — baixe `access_log` (ou os
  rotacionados `*.processed` / `*.gz`). Via SSH/SFTP eles ficam em
  `/var/www/vhosts/system/{dominio}/logs/`.
- **Apache padrão:** `/var/log/apache2/access.log*`
- **Nginx padrão:** `/var/log/nginx/access.log*`

Copie para a máquina local e aponte `--logs` para o arquivo. Os logs **não** são
versionados (`*.log` está no `.gitignore`).

### CLI — Acervo histórico (extração para análise posterior)

Acumula a série **diária** do GSC no grão mais fino (dia × página × query) num
SQLite por site, e gera o pacote que uma sessão de análise consome. **Não
analisa nada** — sem score, sem veredito. A GUI (`py app_acervo.py`) explica o
fluxo em 3 etapas; esta seção cobre o que só existe na CLI.

```bash
py acervo.py aferir   --site www.exemplo.com.br            # 1x por site, ~8 req, nada gravado
py acervo.py backfill --site www.exemplo.com.br            # 1x por site, os ~16 meses que a API guarda
py acervo.py diario   --site www.exemplo.com.br            # SEMANAL, para sempre
py acervo.py pacote   --site www.exemplo.com.br            # snapshot + DADOS.md
```

O `pacote` escreve em `relatorios/{dominio}/acervo/pacote/`, em dois andares:

```
pacote/
  acervo.sqlite3    snapshot do banco INTEIRO (todos os `type` coletados)
  eventos.csv       a timeline anotada à mão — do acervo, não de um tipo
  evento_urls.csv   uma linha por (evento, URL informada), com o casamento
  extras/           onde largar exports manuais da UI do GSC
  web/
    DADOS.md        a escrituração do `type` web — leia ANTES de concluir nada
    consultas.sql   consultas prontas, já com `WHERE tipo = 'web'`
  image/            o mesmo para image, se você gerou esse tipo também
```

A raiz é compartilhada; a subpasta é o que é de **um** `type`.

O `diario` é a parte que **não pode falhar**: a retenção da API é uma janela
móvel de ~16 meses, então cada semana sem rodar apaga para sempre a semana mais
antiga. É ele que faz 16 meses virarem 2 anos.

```bash
schtasks /Create /TN "GSC Acervo Semanal" /SC WEEKLY /D MON /ST 07:00 /TR "cmd /c cd /d E:\projetos\projetoprst.com.br\gsc-monitor && py acervo.py diario --site www.exemplo.com.br"
```

#### `--tipos`: `web` é menos da metade do que o site recebe

A Search Analytics separa as superfícies de busca em `type`, e o padrão de todo
comando é **só `web`**. Dependendo do nicho, `image` pode ter **mais impressões
que `web`** — e cair em magnitude e em data diferentes dele, inclusive sem a
quebra brusca que o `web` sofreu. Nesses casos, coletar só `web` não é um
recorte menor do mesmo fato: é outro fato. É também o que permite distinguir
queda específica de uma superfície de punição de site inteiro, já que uma
demoção de domínio derrubaria as duas. Rode o `--dry-run` com `--tipos` no seu
site para medir em vez de supor.

```bash
py acervo.py backfill --site www.exemplo.com.br --tipos web,image
py acervo.py diario   --site www.exemplo.com.br --tipos web,image
py acervo.py backfill --site www.exemplo.com.br --tipos web,image --dry-run   # custo por tipo
```

`--tipo` (singular) continua valendo para um tipo só; os dois são mutuamente
exclusivos. `video`, `news`, `discover` e `googleNews` existem e costumam vir
vazios — o `--dry-run` mostra o custo antes de gastar requisição.

> **A armadilha:** `image` **não** entra no default, de propósito — ligá-lo
> dobraria o custo e o tamanho do banco de quem já tem tarefa agendada, sem
> pedir. Mas se você fizer o `backfill` com `--tipos web,image` e agendar o
> `diario` **sem** `--tipos`, a série de `image` para de crescer e a janela
> móvel vai comendo o que já foi coletado. **O `--tipos` do `diario` tem de
> espelhar o do `backfill`.** O `status` lista a cobertura por tipo e nomeia os
> que nunca foram coletados, justamente para isso aparecer.

O `pacote` tem o mesmo par de flags, mais uma terceira forma:

```bash
py acervo.py pacote --site www.exemplo.com.br --tipos web,image   # os dois documentos
py acervo.py pacote --site www.exemplo.com.br --todos-os-tipos    # todo tipo coletado
py acervo.py pacote --site www.exemplo.com.br --tipo image        # só este
```

Cada `type` ganha o SEU `pacote/{tipo}/DADOS.md`, e gerar um **nunca** sobrescreve
o do outro. O snapshot é **um só**, na raiz: é `Connection.backup()` do banco
inteiro, logo já contém todos os tipos e é idêntico para qualquer `--tipo` —
duplicá-lo custaria centenas de MB (439 MB no site-piloto) sem ganho nenhum. Por
isso `--tipos web,image` numa chamada é melhor que rodar o comando duas vezes:
copia o snapshot uma vez. `--sem-snapshot` regenera só os documentos e declara,
no próprio `DADOS.md`, que o snapshot é de uma geração anterior.

A seção 11 do `DADOS.md` declara qual tipo aquele documento cobre, diz que as
linhas dos outros tipos coletados **estão no snapshot** (consultáveis com
`WHERE tipo = ...`, já que o recorte é só do texto) e nomeia os tipos que nunca
foram coletados — para ausência de coleta nunca ser lida como ausência de
tráfego.

---

## Relatórios gerados

Todos os arquivos ficam em `relatorios/{dominio}/`:

| Arquivo | Conteúdo |
|---------|----------|
| `YYYY-MM-DD_posicao.json` | Dados brutos de posicionamento |
| `YYYY-MM-DD_posicao.xlsx` | Excel com abas: Resumo, Posicionamento, Oportunidades CTR, Histórico, Trends, Canibalização, Sem Impressões |
| `dashboard.html` | Dashboard interativo com gráficos Chart.js |
| `YYYY-MM-DD_indexacao.json` | Dados brutos de indexação |
| `_batch/YYYY-MM-DD_resumo.csv` | Resumo consolidado do modo batch (`--batch-report`) |
| `YYYY-MM-DD_redirects.csv` | **Sugestão** de consolidação 301 (gerado quando há canibalização, via `--queries`) |
| `YYYY-MM-DD_redirects_apache.txt` | Bloco `.htaccess` (Apache) com os 301 sugeridos |
| `YYYY-MM-DD_redirects_nginx.txt` | Bloco `server {}` (nginx) com os 301 sugeridos |
| `poda/YYYY-MM-DD_poda.csv` | Plano de Poda **editável**: URLs antigas (fora do sitemap) com ação sugerida |
| `poda/YYYY-MM-DD_poda_apache.txt` | Bloco `.htaccess` compilado do plano de poda revisado (410/404/301) — `RedirectMatch` ancorado |
| `poda/YYYY-MM-DD_poda_redirect.txt` | Mesmo plano no estilo `Redirect 301 /caminho/ destino` do mod_alias (diretiva simples; **prefix-match**) |
| `poda/YYYY-MM-DD_poda_nginx.txt` | Bloco `server {}` compilado do plano de poda revisado |
| `poda/YYYY-MM-DD_poda.php` | Versão PHP do plano compilado — `require` no topo do `index.php`/`wp-config.php` |
| `YYYY-MM-DD_crawl.html` | Dashboard de crawl budget (Googlebot via access log) |
| `YYYY-MM-DD_crawl.json/.csv/.txt` | Crawl por URL, nunca-rastreadas e money pages subcrawladas |

> Os artefatos do Plano de Poda ficam na subpasta dedicada
> `relatorios/{dominio}/poda/`.

### Plano de Consolidação 301 (sugestão)

Quando a análise de canibalização (`--queries`) encontra grupos de URLs
competindo pela mesma keyword, a ferramenta gera automaticamente um **plano de
consolidação 301**: para cada grupo, escolhe a URL canônica (mais cliques →
melhor posição → mais impressões) e lista as demais como origens de redirect.
O plano sai em três formatos prontos para aplicar (CSV + Apache + nginx), além
da sheet "Plano 301" no Excel e de uma seção no dashboard.

> ⚠ **O plano é uma sugestão automática — nunca aplique sem revisão humana.**
> Confirme que as páginas são de fato redundantes (e não intencionalmente
> distintas) antes de criar redirects 301, que são difíceis de reverter.
> Conflitos entre grupos (URL canônica em um grupo e concorrente em outro) são
> resolvidos por prioridade de severidade e listados nos artefatos.

### Plano de Poda (sugestão)

O Plano de Poda cruza as páginas que o Google exibiu na busca (Search
Analytics, 30 dias) com o sitemap. URLs fora do sitemap são páginas antigas:

- **Sem tráfego** → ação sugerida `410` (remoção limpa; o Google esquece a
  URL mais rápido do que com 404 passivo).
- **Com tráfego** (cliques > 0 ou impressões ≥ piso) → ação `revisar`: é uma
  oportunidade de capturar as impressões com um 301 — **quem decide é o
  analista**, nunca a ferramenta. Quando possível, o plano sugere um destino
  por query compartilhada com página ativa ou por slug semelhante. O destino
  sugerido é sempre uma URL **do sitemap atual** (a sugestão é canonizada para
  a forma exata listada no sitemap — uma página comprovadamente ativa).
  Quando nenhum destino relevante é encontrado, a URL "revisar" recebe a
  **home como sugestão de último recurso** (marcada `home (fallback)`), para
  não deixar a célula `destino_final` em branco — desligue com
  `--sem-fallback-home` (ou o checkbox na GUI). É uma sugestão **fraca**: o
  Google trata redirect em massa para a home como soft-404, então a ação
  permanece `revisar` e a compilação avisa se muitas virarem 301. URLs sem
  tráfego (`410`) não recebem o fallback.

O CSV gerado é o próprio arquivo de trabalho do analista: edite `acao_final`
(`410`/`404`/`301`/`manter`) e `destino_final` (colunas logo após a URL, já
pré-preenchidas com a sugestão), depois compile (`--compilar` ou botão
"2 · Compilar blocos" na GUI). A compilação gera **quatro formatos** com a mesma
semântica: bloco `.htaccess` (Apache, `RedirectMatch` ancorado), o mesmo plano
no estilo `Redirect` simples do mod_alias (`{data}_poda_redirect.txt` —
`Redirect 301 /caminho/ destino`, para quem prefere a diretiva direta ou usa
painéis tipo cPanel; atenção: faz **prefix-match** e URLs com query ficam só
como comentário), bloco `server {}` (nginx) e um
`{data}_poda.php` standalone — para hospedagens onde não dá para editar a
config do servidor (Plesk/shared hosting) ou onde o CMS sobrescreve o
`.htaccess`: copie para a raiz e adicione `require __DIR__ . '/{data}_poda.php';`
no topo do `index.php` (em WordPress, no início do `wp-config.php`, que
sobrevive a updates do core). O arquivo usa
delimitador `;` e decimais com vírgula — abre direto em colunas no Excel
brasileiro; a coluna `origem` distingue URLs vistas na busca (`busca`) das
importadas do export (`export-gsc`). Queries navegacionais de marca não geram
sugestão de destino (casariam com qualquer página).

> ⚠ **Nunca redirecione tudo para a home** — o Google trata redirect em massa
> para a home como soft-404 (não passa valor). A ferramenta avisa quando
> detecta esse padrão. URLs marcadas `revisar` não entram nos blocos.

---

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Saída esperada: **482 testes OK**. Toda a suíte roda no pytest (config em
`pytest.ini`); as chamadas de rede são mockadas, então nenhum teste gasta cota.
A CI ainda aplica um piso de cobertura (40%).

---

## Estrutura do projeto

```
gsc-monitor/
  app.py          ← entrada GUI (posicionamento/indexação)
  app_poda.py     ← entrada GUI: Plano de Poda
  app_acervo.py   ← entrada GUI: Acervo histórico (fluxo guiado em 3 etapas)
  posicao.py      ← CLI: posicionamento
  main.py         ← CLI: indexação
  poda.py         ← CLI: Plano de Poda (gerar/compilar)
  logs.py         ← CLI: crawl budget (Googlebot via access log, local)
  config.py       ← BASE_DIR + constantes transversais
  core/           ← lógica de negócio
    auth.py       ← OAuth2 Google
    cache.py      ← cache JSON por domínio
    storage.py    ← I/O de arquivos
    analytics.py  ← health score, páginas sem impressões, canibalização
    pruning.py    ← Plano de Poda: diff GSC × sitemap, sugestões, blocos
    classifier.py ← mapeamento verdict → categoria
    sitemap.py    ← parser de sitemap.xml
    log_analyzer.py ← parser/agregação de access log (crawl budget; puro,
                      exceto o DNS opt-in de verificação do Googlebot)
  fetchers/       ← integração com APIs externas
    inspector.py         ← URL Inspection API
    position_fetcher.py  ← Search Analytics API
    knowledge_graph.py   ← Knowledge Graph Search API
    nlp_analyzer.py      ← Cloud Natural Language API
    trends_fetcher.py    ← Google Trends via pytrends
  reporters/      ← geração de saída
    reporter.py          ← relatórios de indexação
    position_reporter.py ← relatórios de posicionamento
    excel_reporter.py    ← geração de Excel
    html_reporter.py     ← dashboard HTML
    crawl_reporter.py    ← relatório de crawl budget (HTML/TXT)
  gui/
    main_window.py ← janela Tkinter principal
    runner.py      ← execução em thread
    poda_window.py ← janela do Plano de Poda (app_poda.py)
    poda_runner.py ← execução em thread das etapas de poda
    acervo_window.py ← janela do Acervo (app_acervo.py)
    acervo_runner.py ← execução em thread dos comandos do acervo
    terminal.py    ← paleta e colorização compartilhadas das 3 janelas
  tests/             ← suíte pytest: test_storage, test_cache, test_analytics,
                       test_ctr, test_classifier, test_sitemap, test_content_quality,
                       test_position_fetcher, test_log_analyzer, test_crawl_reporter,
                       test_phase5 (APIs), test_phase6 (dashboard)
  relatorios/
    {dominio}/     ← arquivos por domínio
      .cache/      ← cache de API
      dashboard.html
      YYYY-MM-DD_*.json/xlsx/csv
```

---

## Notas

- O cache tem TTL de 72h para posicionamento/NLP e 24h para indexação. Use `--no-cache` para forçar dados frescos.
- `--trends` usa por padrão a dimensão `date` do GSC (oficial, sem dependência extra). `pytrends` só é necessário para o caminho legado `--trends-source pytrends`.
- O dashboard HTML é gerado automaticamente a cada execução de posicionamento.
- A flag `--nlp` consome cota da Cloud Natural Language API (2 unidades por URL, gratuito até 5.000/mês).
- `logs.py` analisa o access log do servidor **localmente** (crawl budget do Googlebot), **sem cota de API**; aceita `.gz` e múltiplos arquivos. Combine com `--gsc` (após rodar `posicao.py`) para cruzar crawl × impressões.
