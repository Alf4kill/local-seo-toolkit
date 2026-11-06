"""
cache.py — Cache em JSON para resultados das APIs do Google Search Console.

Estrutura em disco:
    relatorios/{dominio}/.cache/
        inspect_YYYY-MM-DD.json      ← URL Inspection API  (por dia)
        posicao_START_END.json       ← Search Analytics API (por período)

TTL padrão:
    Indexação  : 24 h  — re-inspeciona no dia seguinte
    Posicionamento : 72 h  — dados do GSC têm delay de 2-3 dias, não mudam mais rápido

TTL por veredito (indexação): o arquivo do dia continua valendo 24 h para
tudo, mas load_inspect_window() também varre os dias ANTERIORES e reaproveita
só os resultados PASS (página indexada), que mudam de estado devagar. Isso
existe porque a cota da URL Inspection é 2.000/dia POR SITE: num site de ~870
páginas, reinspecionar tudo todo dia consome metade da cota sem informação
nova. Problemas (FAIL/NEUTRAL/unknown) nunca são reaproveitados de dias
anteriores — são exatamente o que precisa de releitura.
"""

import json
import os
import re
from datetime import UTC, date, datetime, timedelta

from core.storage import _get_domain_dir

CACHE_SUBDIR = ".cache"
TTL_INSPECT_HOURS = 24  # URL Inspection API
TTL_POSICAO_HOURS = 72  # Search Analytics API


# ---------------------------------------------------------------------------
# Helpers internos de I/O
# ---------------------------------------------------------------------------


def _cache_dir(site: str) -> str:
    """Retorna (e cria) a pasta de cache do domínio."""
    path = os.path.join(_get_domain_dir(site), CACHE_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_key(key: str) -> str:
    """Remove caracteres inválidos do nome do arquivo de cache."""
    return re.sub(r"[^\w\-.]", "_", key)


def _cache_path(site: str, key: str) -> str:
    return os.path.join(_cache_dir(site), f"{_safe_key(key)}.json")


def _read_entry(path: str) -> dict | None:
    """Lê um arquivo de cache. Retorna None em caso de erro ou ausência."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_entry(path: str, data) -> None:
    """Persiste dados no cache com timestamp de gravação."""
    entry = {
        # UTC explícito (ciente de fuso) — instante inequívoco, imune a DST /
        # mudança de fuso do host. Entradas antigas (horário local ingênuo) são
        # tratadas por _is_fresh para retrocompatibilidade.
        "cached_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def _is_fresh(entry: dict, max_age_hours: float) -> bool:
    """Verifica se o cache ainda está dentro do TTL."""
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
    except (KeyError, ValueError):
        return False
    # Compat: caches antigos gravavam horário local ingênuo (sem fuso).
    # Interpreta-os como horário local do host e os torna cientes do fuso,
    # para comparar instantes (não relógios de parede) com o "agora" em UTC.
    if cached_at.tzinfo is None:
        cached_at = cached_at.astimezone()
    return (datetime.now(UTC) - cached_at) <= timedelta(hours=max_age_hours)


# ---------------------------------------------------------------------------
# Cache de posicionamento  (Search Analytics — resposta completa do domínio)
# ---------------------------------------------------------------------------


def get_posicao_cache(site: str, start_date: str, end_date: str) -> dict | None:
    """
    Retorna o dict {url → métricas} cacheado para o período, ou None se
    expirado / inexistente.
    """
    key = f"posicao_{start_date}_{end_date}"
    entry = _read_entry(_cache_path(site, key))
    if entry is None or not _is_fresh(entry, TTL_POSICAO_HOURS):
        return None
    return entry["data"]


def set_posicao_cache(site: str, start_date: str, end_date: str, api_data: dict) -> None:
    """Persiste o api_data (dict URL → métricas) no cache de posicionamento."""
    key = f"posicao_{start_date}_{end_date}"
    path = _cache_path(site, key)
    _write_entry(path, api_data)
    print(f"[cache] Posicionamento salvo em cache: {os.path.basename(path)}")


# ---------------------------------------------------------------------------
# Cache de inspeção  (URL Inspection API — agrupado por dia, indexado por URL)
# ---------------------------------------------------------------------------
#
# Um único arquivo por dia contém os resultados de todas as URLs inspecionadas
# naquele dia.  Estrutura interna do JSON:
#   { "cached_at": "...", "data": { "https://...": {result}, ... } }
#
# O cache é atualizado de forma incremental: a cada nova URL inspecionada o
# arquivo é relido, a entrada da URL é adicionada/atualizada e o arquivo é
# regravado.  Isso garante que uma execução interrompida não perde os
# resultados já obtidos.
# ---------------------------------------------------------------------------


def _load_inspect_day(site: str, date_str: str) -> dict | None:
    """
    Carrega o arquivo de cache de inspeção do dia.
    Retorna o dict {url → result} se válido, None se expirado ou inexistente.
    """
    key = f"inspect_{date_str}"
    entry = _read_entry(_cache_path(site, key))
    if entry is None or not _is_fresh(entry, TTL_INSPECT_HOURS):
        return None
    return entry["data"]


def get_inspect_cache(site: str, date_str: str, url: str) -> dict | None:
    """
    Retorna o resultado cacheado de inspeção para uma URL específica no dia
    dado. Retorna None se não encontrado ou expirado.
    """
    day_cache = _load_inspect_day(site, date_str)
    if day_cache is None:
        return None
    return day_cache.get(url)


def load_inspect_window(site: str, date_str: str, ttl_ok_days: int = 0) -> dict:
    """
    Carrega de uma vez só o mapa {url → result} aproveitável para uma execução.

    Substitui o padrão antigo de chamar get_inspect_cache() por URL, que
    reabria e reparseava o arquivo do dia a cada uma das N URLs (1,1 s em 874
    URLs, e crescendo com o tamanho do site).

    Regras:
        - arquivo do dia (date_str): vale para QUALQUER veredito, dentro do
          TTL de 24 h — é o comportamento histórico, preservado;
        - dias anteriores, até ttl_ok_days atrás: só entram resultados com
          verdict == "PASS" (página indexada). Um resultado de hoje sempre
          ganha de um resultado mais antigo da mesma URL.

    ttl_ok_days = 0 desliga a janela estendida (só o arquivo do dia).
    """
    janela: dict[str, dict] = {}

    # Dos mais antigos para os mais novos: o dia de hoje sobrescreve por último.
    if ttl_ok_days and ttl_ok_days > 0:
        try:
            hoje = date.fromisoformat(date_str)
        except ValueError:
            hoje = None
        if hoje is not None:
            for atras in range(ttl_ok_days, 0, -1):
                dia = (hoje - timedelta(days=atras)).isoformat()
                # Dias anteriores são lidos pela DATA do arquivo, não pelo
                # cached_at: o TTL aqui é a janela em dias, não as 24 h.
                entry = _read_entry(_cache_path(site, f"inspect_{dia}"))
                if entry is None or not isinstance(entry.get("data"), dict):
                    continue
                for url, result in entry["data"].items():
                    if isinstance(result, dict) and result.get("verdict") == "PASS":
                        janela[url] = result

    hoje_cache = _load_inspect_day(site, date_str)
    if hoje_cache:
        janela.update(hoje_cache)

    return janela


def set_inspect_cache_bulk(site: str, date_str: str, results: dict) -> None:
    """
    Grava vários resultados no cache do dia numa única leitura + escrita.

    Mesma semântica de set_inspect_cache (mescla com o que já existe, ignora o
    TTL na escrita), mas sem o custo O(n²) de reescrever o arquivo inteiro a
    cada URL — eram 14,9 s de disco puro em 874 URLs.
    """
    if not results:
        return
    key = f"inspect_{date_str}"
    path = _cache_path(site, key)
    entry = _read_entry(path)
    url_cache = entry["data"] if (entry and isinstance(entry.get("data"), dict)) else {}
    url_cache.update(results)
    _write_entry(path, url_cache)


# ---------------------------------------------------------------------------
# Cache de queries (Search Analytics — dimensão [query, page])
# ---------------------------------------------------------------------------

TTL_QUERY_HOURS = 72  # mesmo TTL que posicionamento


def get_query_cache(site: str, start_date: str, end_date: str) -> "list | None":
    """Retorna a lista cacheada de rows [query×page], ou None se expirado."""
    key = f"posicao_queries_{start_date}_{end_date}"
    entry = _read_entry(_cache_path(site, key))
    if entry is None or not _is_fresh(entry, TTL_QUERY_HOURS):
        return None
    return entry["data"]


def set_query_cache(site: str, start_date: str, end_date: str, rows: list) -> None:
    """Persiste a lista de rows [query×page] no cache."""
    key = f"posicao_queries_{start_date}_{end_date}"
    path = _cache_path(site, key)
    _write_entry(path, rows)
    print(f"[cache] Queries salvas em cache: {os.path.basename(path)}")


# ---------------------------------------------------------------------------
# Cache de tendências por data (P5 — Search Analytics, dimensões [date] e
# [date, query]). Substitui o pytrends como fonte padrão de tendências.
# ---------------------------------------------------------------------------

TTL_DATE_TRENDS_HOURS = 24  # 1 dia novo de dados por dia — TTL curto


def get_date_trends_cache(site: str, start_date: str, end_date: str) -> "dict | None":
    """Retorna o dict cacheado de fetch_date_trends, ou None se expirado."""
    key = f"date_trends_{start_date}_{end_date}"
    entry = _read_entry(_cache_path(site, key))
    if entry is None or not _is_fresh(entry, TTL_DATE_TRENDS_HOURS):
        return None
    return entry["data"]


def set_date_trends_cache(site: str, start_date: str, end_date: str, data: dict) -> None:
    """Persiste o resultado bruto de fetch_date_trends no cache."""
    key = f"date_trends_{start_date}_{end_date}"
    path = _cache_path(site, key)
    _write_entry(path, data)
    print(f"[cache] Tendências por data salvas em cache: {os.path.basename(path)}")


def set_inspect_cache(site: str, date_str: str, url: str, result: dict) -> None:
    """
    Persiste o resultado de inspeção de uma URL no cache do dia de forma
    incremental (mantém os resultados já armazenados das outras URLs).
    """
    key = f"inspect_{date_str}"
    path = _cache_path(site, key)
    entry = _read_entry(path)

    # Aproveita entradas já existentes mesmo se o arquivo "expirou" — o TTL
    # é usado apenas para leitura (get), não para escrita (set).
    url_cache = entry["data"] if (entry and isinstance(entry.get("data"), dict)) else {}
    url_cache[url] = result
    _write_entry(path, url_cache)
