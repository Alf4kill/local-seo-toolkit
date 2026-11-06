"""
sitemap.py — Fetch e parse do sitemap.xml do domínio informado.
Suporta sitemapindex (sitemaps aninhados) e fallback via robots.txt.

Retentativa e honestidade no erro
---------------------------------
A versão anterior engolia QUALQUER requests.RequestException (e qualquer
status != 2xx) devolvendo None, sem retentar, e terminava afirmando
"Nenhum sitemap encontrado — verifique se o sitemap é público". Isso
transformava uma falha transitória do servidor numa acusação errada sobre a
configuração do site: visto na prática num site atrás de Cloudflare que
devolvia **521** (origem fora do ar) em ~1 de cada 4 requisições — a etapa de
indexação falhava e a de posicionamento, segundos depois, baixava o mesmo
sitemap com 874 URLs.

Agora:
  - falhas TRANSITÓRIAS (timeout, erro de conexão, 429 e 5xx, incluindo a
    família 52x do Cloudflare) são retentadas com backoff exponencial + jitter;
  - falhas PERMANENTES (404, 403 e demais 4xx) não são retentadas — esperar não
    faz um sitemap ausente aparecer;
  - a mensagem de erro final DIZ o que aconteceu em cada candidato, e só fala
    em "sitemap ausente" quando de fato foram respostas 404.

Sub-sitemap que falha interrompe a execução em vez de devolver lista parcial:
várias partes do projeto (a poda, em especial) tratam o sitemap como a
whitelist completa de páginas ativas, então uma lista truncada em silêncio
marcaria página viva como fantasma e a mandaria para 410.

`dormir` e `jitter` são injetáveis para os testes rodarem instantâneos —
mesma convenção de fetchers/gsc_retry.py.
"""

import random
import time
import xml.etree.ElementTree as ET

import requests

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
TIMEOUT = 15  # segundos

# Identifica a ferramenta em vez do "python-requests/x.y" padrão, que parte dos
# WAFs bloqueia de saída.
USER_AGENT = "gsc-monitor/1.0 (+ferramenta local de análise de Search Console)"

SITEMAP_TENTATIVAS = 3  # 1 tentativa + 2 retentativas
SITEMAP_BACKOFF_BASE = 1.5  # s; 1ª espera ~1.5s, 2ª ~2.2s (+ jitter)

# Transitórios: vale a pena esperar e tentar de novo.
#   408 Request Timeout      429 Too Many Requests
#   5xx comuns do servidor
#   520-527: família Cloudflare "a origem falhou" — 521 é "Web Server Is Down"
CODIGOS_TRANSITORIOS = frozenset(
    {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 527}
)


def _get(
    url: str,
    tentativas: int = SITEMAP_TENTATIVAS,
    dormir=time.sleep,
    jitter=random.random,
    silencioso: bool = False,
) -> tuple[requests.Response | None, str]:
    """
    Faz GET na URL, retentando falhas transitórias.

    Retorna (Response, "") em caso de sucesso e (None, motivo) em caso de
    falha. O motivo é texto legível ("HTTP 521", "ConnectTimeout: ...") e
    existe para a mensagem de erro poder dizer a verdade sobre o que houve,
    em vez de chutar.
    """
    motivo = "sem tentativa"

    for tentativa in range(1, max(1, tentativas) + 1):
        transitorio = False
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            if resp.status_code < 400:
                return resp, ""
            motivo = f"HTTP {resp.status_code}"
            transitorio = resp.status_code in CODIGOS_TRANSITORIOS
        except requests.RequestException as exc:
            # Timeout e erro de conexão são o caso transitório clássico.
            motivo = f"{type(exc).__name__}"
            detalhe = str(exc).strip()
            if detalhe:
                motivo = f"{motivo}: {detalhe[:160]}"
            transitorio = True

        if not transitorio or tentativa >= tentativas:
            break

        espera = SITEMAP_BACKOFF_BASE**tentativa + jitter() * 0.5
        if not silencioso:
            print(
                f"[sitemap] {motivo} em {url}; nova tentativa em {espera:.1f}s "
                f"({tentativa}/{tentativas})."
            )
        dormir(espera)

    return None, motivo


def _parse_sitemap(content: str) -> tuple[list[str], list[str]]:
    """
    Recebe o conteúdo XML de um sitemap e retorna (urls_de_pagina, urls_de_sitemap).
    Se for um sitemapindex, as URLs vêm na segunda posição.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return [], []

    tag = root.tag.lower()

    if "sitemapindex" in tag:
        sitemap_urls = [
            loc.text.strip() for loc in root.findall(f".//{{{SITEMAP_NS}}}loc") if loc.text
        ]
        return [], sitemap_urls

    page_urls = [loc.text.strip() for loc in root.findall(f".//{{{SITEMAP_NS}}}loc") if loc.text]
    return page_urls, []


def _sitemap_from_robots(domain: str, **kw) -> str | None:
    """Lê robots.txt e extrai a primeira diretiva Sitemap: encontrada."""
    for scheme in ("https", "http"):
        # silencioso: o robots.txt é só um fallback; retentativa dele não
        # precisa poluir o terminal com o mesmo aviso duas vezes.
        resp, _ = _get(f"{scheme}://{domain}/robots.txt", silencioso=True, **kw)
        if resp is None:
            continue
        for line in resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                url = line.split(":", 1)[1].strip()
                return url
    return None


def _motivo_e_transitorio(motivo: str) -> bool:
    """Classifica um motivo de falha (texto de _get) como transitório ou não."""
    if motivo.startswith("HTTP "):
        codigo = motivo.split()[1]
        return codigo.isdigit() and int(codigo) in CODIGOS_TRANSITORIOS
    # Qualquer outra coisa é exceção de rede (timeout, conexão, DNS, TLS).
    return True


def _mensagem_de_falha(domain: str, falhas: list[tuple[str, str]]) -> str:
    """
    Monta a mensagem de erro dizendo o que REALMENTE aconteceu.

    Só afirma que o sitemap não existe quando todas as respostas foram 404.
    Se houve transitório (521, timeout...), diz que o servidor falhou — é
    outro problema, com outra ação.
    """
    detalhe = "\n".join(f"  - {url} → {motivo}" for url, motivo in falhas)
    motivos = [motivo for _, motivo in falhas]

    todos_404 = bool(motivos) and all(m.startswith("HTTP 404") for m in motivos)
    houve_transitorio = any(_motivo_e_transitorio(m) for m in motivos)

    if todos_404:
        diagnostico = (
            "Todos os endereços responderam 404: o sitemap realmente não está "
            "nesses caminhos. Verifique o domínio e onde o sitemap é publicado."
        )
    elif houve_transitorio:
        diagnostico = (
            "O servidor falhou de forma TRANSITÓRIA (timeout, erro de conexão ou "
            "5xx — a família 52x indica origem fora do ar atrás de um CDN como o "
            "Cloudflare), e as retentativas não foram suficientes. Isso NÃO "
            "significa que o sitemap não existe ou não é público: tente de novo "
            "em alguns minutos."
        )
    else:
        diagnostico = (
            "O servidor recusou o acesso (resposta 4xx). O sitemap pode existir "
            "mas estar bloqueado para clientes automatizados."
        )

    return f"Nao foi possivel obter o sitemap de '{domain}'.\n{detalhe}\n{diagnostico}"


def fetch_urls(domain: str, dormir=time.sleep, jitter=random.random) -> list[str]:
    """
    Ponto de entrada: recebe o domínio (ex: 'exemplo.com.br') e retorna
    a lista completa de URLs de páginas encontradas nos sitemaps.

    Levanta RuntimeError se nenhum sitemap pôde ser obtido, OU se um
    sub-sitemap do índice falhou — nesse segundo caso a lista existiria, mas
    incompleta, e devolvê-la como se fosse a lista de páginas ativas é o tipo
    de erro silencioso que faz a poda marcar página viva como fantasma.
    """
    kw = {"dormir": dormir, "jitter": jitter}

    candidates = [
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"http://{domain}/sitemap.xml",
        f"http://{domain}/sitemap_index.xml",
    ]

    root_sitemap_url = None
    root_content = None
    falhas: list[tuple[str, str]] = []

    for url in candidates:
        resp, motivo = _get(url, **kw)
        if resp is not None:
            root_sitemap_url = url
            root_content = resp.text
            break
        falhas.append((url, motivo))

    if root_content is None:
        # Última tentativa: robots.txt
        robots_sitemap = _sitemap_from_robots(domain, **kw)
        if robots_sitemap:
            resp, motivo = _get(robots_sitemap, **kw)
            if resp:
                root_sitemap_url = robots_sitemap
                root_content = resp.text
            else:
                falhas.append((robots_sitemap, f"{motivo} (via robots.txt)"))

    if root_content is None:
        raise RuntimeError(_mensagem_de_falha(domain, falhas))

    print(f"[sitemap] Sitemap raiz: {root_sitemap_url}")

    page_urls, sub_sitemap_urls = _parse_sitemap(root_content)

    # Resolve sitemaps aninhados (até 1 nível de profundidade)
    sub_falhos: list[tuple[str, str]] = []
    for sub_url in sub_sitemap_urls:
        print(f"[sitemap] Sub-sitemap: {sub_url}")
        resp, motivo = _get(sub_url, **kw)
        if resp is None:
            print(f"[sitemap] ERRO — não foi possível obter: {sub_url} ({motivo})")
            sub_falhos.append((sub_url, motivo))
            continue
        urls, _ = _parse_sitemap(resp.text)
        page_urls.extend(urls)

    if sub_falhos:
        detalhe = "\n".join(f"  - {url} → {motivo}" for url, motivo in sub_falhos)
        raise RuntimeError(
            f"{len(sub_falhos)} de {len(sub_sitemap_urls)} sub-sitemap(s) de "
            f"'{domain}' nao puderam ser obtidos:\n{detalhe}\n"
            "A lista de URLs ficaria INCOMPLETA, e varias analises (a poda, em "
            "especial) tratam o sitemap como a lista completa de paginas ativas "
            "— uma lista truncada marcaria pagina viva como fantasma. "
            "Execute de novo em alguns minutos."
        )

    # Remove duplicatas mantendo ordem
    seen = set()
    unique_urls = []
    for url in page_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    print(f"[sitemap] Total de URLs únicas encontradas: {len(unique_urls)}")
    return unique_urls
