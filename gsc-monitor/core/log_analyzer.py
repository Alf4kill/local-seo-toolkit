"""
log_analyzer.py — Análise de crawl budget a partir do access log do servidor.

100% local, sem cota de API. Lê o log de acesso (Apache/Nginx, formato
"combined") e mede o comportamento REAL do Googlebot:
  - frequência de crawl por URL (hits, último acesso, mix de status, bytes),
  - separação bot x humano (com aviso de que UA é falsificável),
  - páginas do sitemap NUNCA rastreadas no período do log,
  - "money pages" do GSC com muitas impressões mas zero crawl (subcrawladas),
  - desperdício de crawl em URLs com query string (parâmetros/duplicatas) e 404.

Honestidade analítica: a detecção por User-Agent é FALSIFICÁVEL. verify_googlebot()
confirma por DNS reverso+direto (opt-in, lento). O resultado sempre carrega o
flag `resolved` para o relatório deixar claro se a contagem é "por UA" ou
"verificada por DNS".

A lógica é pura e streamável: `analyze_lines(iterable)` faz toda a agregação sem
tocar em disco/rede; `analyze_logs(paths)` é um wrapper fino que abre o(s)
arquivo(s) (inclusive .gz) e alimenta `analyze_lines`. Isso mantém o núcleo
testável com fixtures em memória.
"""

from __future__ import annotations

import gzip
import os
import re
import socket
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from config import (
    CRAWL_TOP_N,
    GOOGLEBOT_UA_PATTERNS,
    LOG_FORMATS,
    UNDERCRAWLED_MIN_IMPRESSIONS,
)

# Regexes compiladas uma vez a partir das strings declarativas do config.
_COMPILED_FORMATS = {name: re.compile(pat) for name, pat in LOG_FORMATS.items()}

# Meses em inglês — access logs usam SEMPRE nomes ingleses, independentemente do
# locale do SO. Parse manual evita depender de strptime("%b"), que varia com o
# locale (ex.: "Out" em vez de "Oct" numa máquina pt-BR).
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip

# Hosts que comprovam um IP do Google (sufixos do PTR reverso).
_GOOGLE_HOSTS = (".googlebot.com", ".google.com", ".googleusercontent.com")

# Pistas amplas de "algum robô" (para o split humano x outro-bot).
_GENERIC_BOT_HINTS = ("bot", "spider", "crawler", "slurp")

_TS_RE = re.compile(
    r"(?P<d>\d{2})/(?P<mon>[A-Za-z]{3})/(?P<y>\d{4}):"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})\s*(?P<tz>[+-]\d{4})?"
)


# ---------------------------------------------------------------------------
# Parsing puro
# ---------------------------------------------------------------------------


def parse_timestamp(raw: str) -> datetime | None:
    """
    Converte o timestamp do log ('07/Jun/2026:13:55:36 -0300') em datetime
    (timezone-aware quando há offset). Retorna None se o formato não bater.
    """
    m = _TS_RE.match(raw.strip())
    if not m:
        return None
    month = _MONTHS.get(m["mon"].lower())
    if month is None:
        return None
    try:
        dt = datetime(int(m["y"]), month, int(m["d"]), int(m["h"]), int(m["mi"]), int(m["s"]))
    except ValueError:
        return None
    tz = m["tz"]
    if tz:
        sign = 1 if tz[0] == "+" else -1
        offset = sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5]))
        dt = dt.replace(tzinfo=timezone(offset))
    return dt


def parse_log_line(line: str, pattern: re.Pattern | None = None) -> dict | None:
    """
    Faz parse de uma linha do access log. Tenta os formatos do config na ordem
    (combined → common) ou usa `pattern` se fornecido. Retorna um dict
    normalizado, ou None se a linha for malformada/ininteligível.

    Campos: ip, ts (str cru), datetime (datetime|None), method, path,
            path_only (normalizado, sem query/fragmento), has_query (bool),
            status (int), bytes (int|None), ua (str; '' quando o formato não tem).
    """
    line = line.rstrip("\r\n")
    if not line:
        return None
    candidates = (pattern,) if pattern is not None else tuple(_COMPILED_FORMATS.values())
    for rx in candidates:
        m = rx.match(line)
        if not m:
            continue
        g = m.groupdict()
        status_raw = g.get("status")
        if not (status_raw and status_raw.isdigit()):
            return None
        path = g["path"]
        split = urlsplit(path)
        raw_bytes = g.get("bytes")
        return {
            "ip": g["ip"],
            "ts": g["ts"],
            "datetime": parse_timestamp(g["ts"]),
            "method": g["method"],
            "path": path,
            "path_only": _norm_path(split.path or path),
            "has_query": bool(split.query),
            "status": int(status_raw),
            "bytes": int(raw_bytes) if raw_bytes and raw_bytes.isdigit() else None,
            "ua": g.get("ua") or "",
        }
    return None


def _norm_path(path: str) -> str:
    """
    Normaliza o caminho para cruzamento (sitemap × log × GSC): remove
    query/fragmento, garante barra inicial e tira a barra final redundante
    (exceto na raiz). '' vira '/'.
    """
    path = path.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def is_googlebot(ua: str) -> bool:
    """
    True se o User-Agent casar com algum padrão de GOOGLEBOT_UA_PATTERNS.
    ATENÇÃO: baseado só no UA — falsificável. verify_googlebot() confirma por DNS.
    """
    if not ua:
        return False
    low = ua.lower()
    return any(p in low for p in GOOGLEBOT_UA_PATTERNS)


def is_bot(ua: str) -> bool:
    """Heurística ampla: o UA parece de algum robô (qualquer um, não só Google)."""
    if not ua:
        return False
    low = ua.lower()
    return any(h in low for h in _GENERIC_BOT_HINTS)


# ---------------------------------------------------------------------------
# Verificação de Googlebot por DNS (opt-in, lento)
# ---------------------------------------------------------------------------


def _reverse_dns(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return None


def _forward_dns(host: str) -> list[str]:
    try:
        return socket.gethostbyname_ex(host)[2]
    except OSError:
        return []


def verify_googlebot(ip: str) -> bool:
    """
    Confirma se o IP é realmente do Googlebot por DNS reverso + direto:
      IP -> PTR (deve terminar em .googlebot.com/.google.com/.googleusercontent.com)
         -> resolve o host de volta e confere se inclui o IP.
    Faz DNS (lento) — use como opt-in. Retorna False em qualquer falha.
    """
    host = _reverse_dns(ip)
    if not host:
        return False
    host_l = host.lower().rstrip(".")
    if not host_l.endswith(_GOOGLE_HOSTS):
        return False
    return ip in _forward_dns(host_l)


# ---------------------------------------------------------------------------
# Agregação (núcleo puro)
# ---------------------------------------------------------------------------


def _url_path(url: str) -> str:
    """Extrai o caminho normalizado de uma URL absoluta (sitemap/GSC)."""
    return _norm_path(urlsplit(url).path)


def analyze_lines(
    lines: Iterable[str],
    *,
    sitemap_urls: list[str] | None = None,
    position_report: dict | None = None,
    resolve_googlebot: bool = False,
    format_name: str | None = None,
    top_n: int = CRAWL_TOP_N,
) -> dict:
    """
    Agrega um iterável de linhas de access log num relatório de crawl budget.
    Função PURA (sem IO/rede, salvo DNS opt-in via resolve_googlebot). Veja o
    docstring do módulo para o esquema do dict retornado.
    """
    pattern = _COMPILED_FORMATS[format_name] if format_name else None

    lines_total = lines_parsed = lines_malformed = 0
    has_ua = False
    gb_hits = other_bot = humans = spoofed = 0

    # Agregação por caminho (só Googlebot).
    paths: dict[str, dict] = {}
    status_mix: Counter[str] = Counter()
    error_paths: Counter[str] = Counter()
    param_paths: Counter[str] = Counter()
    daily: Counter[str] = Counter()
    param_hits = 0

    dt_min: datetime | None = None
    dt_max: datetime | None = None

    verify_cache: dict[str, bool] = {}

    def _is_real_googlebot(ip: str) -> bool:
        if ip not in verify_cache:
            verify_cache[ip] = verify_googlebot(ip)
        return verify_cache[ip]

    for line in lines:
        lines_total += 1
        rec = parse_log_line(line, pattern)
        if rec is None:
            lines_malformed += 1
            continue
        lines_parsed += 1

        dt = rec["datetime"]
        if dt is not None:
            naive = dt.replace(tzinfo=None)
            dt_min = naive if dt_min is None or naive < dt_min else dt_min
            dt_max = naive if dt_max is None or naive > dt_max else dt_max

        ua = rec["ua"]
        if ua:
            has_ua = True

        ua_is_gb = is_googlebot(ua)
        gb = False
        if ua_is_gb:
            if resolve_googlebot:
                if _is_real_googlebot(rec["ip"]):
                    gb = True
                else:
                    spoofed += 1
            else:
                gb = True

        if gb:
            gb_hits += 1
            key = rec["path_only"]
            entry = paths.get(key)
            if entry is None:
                entry = paths[key] = {
                    "hits": 0,
                    "status": Counter(),
                    "bytes": 0,
                    "methods": set(),
                    "last_dt": None,
                    "last_raw": "",
                }
            entry["hits"] += 1
            entry["status"][str(rec["status"])] += 1
            entry["bytes"] += rec["bytes"] or 0
            entry["methods"].add(rec["method"])
            if dt is not None:
                naive = dt.replace(tzinfo=None)
                if entry["last_dt"] is None or naive > entry["last_dt"]:
                    entry["last_dt"] = naive
                    entry["last_raw"] = rec["ts"]
                daily[naive.date().isoformat()] += 1
            elif not entry["last_raw"]:
                entry["last_raw"] = rec["ts"]

            status_mix[str(rec["status"])] += 1
            if rec["status"] >= 400:
                error_paths[key] += 1
            if rec["has_query"]:
                param_hits += 1
                param_paths[rec["path"]] += 1
        elif ua_is_gb:
            pass  # Googlebot falsificado (verificação falhou) — já contado em `spoofed`.
        elif is_bot(ua):
            other_bot += 1
        else:
            humans += 1

    by_path = [
        {
            "path": key,
            "hits": e["hits"],
            "last_seen": (e["last_dt"].isoformat() if e["last_dt"] else (e["last_raw"] or None)),
            "status_mix": dict(e["status"]),
            "bytes": e["bytes"],
            "methods": sorted(e["methods"]),
        }
        for key, e in sorted(paths.items(), key=lambda kv: kv[1]["hits"], reverse=True)
    ]

    result: dict = {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "has_user_agent": has_ua,
        "resolved": bool(resolve_googlebot),
        "date_range": {
            "start": dt_min.isoformat() if dt_min else None,
            "end": dt_max.isoformat() if dt_max else None,
        },
        "traffic": {
            "googlebot": gb_hits,
            "other_bots": other_bot,
            "humans": humans,
            "spoofed_googlebot": spoofed,
        },
        "googlebot": {
            "total_hits": gb_hits,
            "unique_paths": len(paths),
            "status_mix": dict(status_mix),
            "param_hits": param_hits,
            "by_path": by_path,
            "top_paths": by_path[:top_n],
            "top_errors": [{"path": p, "hits": n} for p, n in error_paths.most_common(top_n)],
            "top_param": [{"path": p, "hits": n} for p, n in param_paths.most_common(top_n)],
            "daily": dict(sorted(daily.items())),
        },
        "never_crawled": _never_crawled(paths, sitemap_urls),
        "undercrawled_money": _undercrawled_money(paths, position_report),
    }
    return result


def _never_crawled(paths: dict, sitemap_urls: list[str] | None) -> dict | None:
    """URLs do sitemap cujo caminho nunca apareceu nos hits do Googlebot."""
    if not sitemap_urls:
        return None
    crawled = set(paths.keys())
    never = [u for u in sitemap_urls if _url_path(u) not in crawled]
    return {
        "sitemap_total": len(sitemap_urls),
        "crawled": len(sitemap_urls) - len(never),
        "never": len(never),
        "urls": never,
    }


def _undercrawled_money(paths: dict, position_report: dict | None) -> list[dict] | None:
    """
    Money pages do GSC (impressões >= UNDERCRAWLED_MIN_IMPRESSIONS) com ZERO hits
    do Googlebot no período do log — o sinal mais honesto de subcrawl. Ordenado
    por impressões desc.
    """
    if not position_report:
        return None
    crawled = set(paths.keys())
    flagged = []
    for row in position_report.get("urls", []):
        if not row.get("has_data"):
            continue
        impressions = row.get("impressions", 0) or 0
        if impressions < UNDERCRAWLED_MIN_IMPRESSIONS:
            continue
        path = _url_path(row["url"])
        hits = paths[path]["hits"] if path in crawled else 0
        if hits == 0:
            flagged.append(
                {
                    "url": row["url"],
                    "impressions": impressions,
                    "position": row.get("position"),
                    "crawl_hits": hits,
                }
            )
    flagged.sort(key=lambda r: r["impressions"], reverse=True)
    return flagged


# ---------------------------------------------------------------------------
# Wrapper de IO (abre arquivos, inclusive .gz, e faz streaming)
# ---------------------------------------------------------------------------


def analyze_logs(paths: str | os.PathLike | list, **kwargs) -> dict:
    """
    Wrapper de `analyze_lines` que faz streaming de um ou mais arquivos de log
    (aceita .gz transparentemente). `paths` pode ser um caminho único ou lista.
    """
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    paths = [os.fspath(p) for p in paths]

    def _stream() -> Iterator[str]:
        for p in paths:
            opener = gzip.open if p.endswith(".gz") else open
            with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
                yield from fh

    result = analyze_lines(_stream(), **kwargs)
    result["log_paths"] = paths
    return result


# ---------------------------------------------------------------------------
# Saída no terminal (ASCII — código de biblioteca, roda fora do entry point)
# ---------------------------------------------------------------------------


def print_crawl_report(result: dict) -> None:
    """Resumo legível no terminal. ASCII puro (seguro em console cp1252)."""
    sep = "=" * 70
    dash = "-" * 70
    gb = result["googlebot"]
    traffic = result["traffic"]

    print(sep)
    print("  RELATORIO DE CRAWL BUDGET (Googlebot via access log)")
    print(sep)
    dr = result["date_range"]
    if dr["start"]:
        print(f"  Periodo do log : {dr['start']}  ->  {dr['end']}")
    print(
        f"  Linhas         : {result['lines_total']:,} "
        f"({result['lines_parsed']:,} ok, {result['lines_malformed']:,} ignoradas)"
    )
    verif = "verificado por DNS" if result["resolved"] else "por UA (NAO verificado)"
    print(f"  Deteccao bot   : {verif}")
    if not result["has_user_agent"]:
        print("  AVISO: log sem User-Agent (formato 'common') — bot x humano indisponivel.")
    print(dash)
    print(f"  Googlebot      : {traffic['googlebot']:,} hits")
    print(f"  Outros bots    : {traffic['other_bots']:,}")
    print(f"  Humanos        : {traffic['humans']:,}")
    if traffic["spoofed_googlebot"]:
        print(
            f"  Googlebot FALSO: {traffic['spoofed_googlebot']:,} (UA dizia Googlebot; DNS negou)"
        )
    print(dash)

    print(f"  URLs distintas rastreadas: {gb['unique_paths']:,}")
    if gb["status_mix"]:
        mix = "  ".join(f"{code}:{n}" for code, n in sorted(gb["status_mix"].items()))
        print(f"  Status (Googlebot): {mix}")
    if gb["param_hits"]:
        print(
            f"  Crawl em URLs com parametro (?): {gb['param_hits']:,} hits (possivel desperdicio)"
        )
    print(dash)

    print("  TOP URLs por frequencia de crawl:")
    for r in gb["top_paths"][:15]:
        last = (r["last_seen"] or "")[:10]
        print(f"    {r['hits']:>6}x  {last:<10}  {r['path']}")

    if gb["top_errors"]:
        print(dash)
        print("  Crawl desperdicado em ERROS (status >= 400):")
        for r in gb["top_errors"][:10]:
            print(f"    {r['hits']:>6}x  {r['path']}")

    nc = result.get("never_crawled")
    if nc:
        print(dash)
        print(f"  Paginas do sitemap NUNCA rastreadas: {nc['never']:,} de {nc['sitemap_total']:,}")
        for u in nc["urls"][:10]:
            print(f"    - {u}")
        if nc["never"] > 10:
            print(f"    ... (+{nc['never'] - 10})")

    um = result.get("undercrawled_money")
    if um:
        print(dash)
        print(f"  MONEY PAGES subcrawladas (muitas impressoes, ZERO crawl): {len(um)}")
        for r in um[:10]:
            pos = f"{r['position']:.1f}" if isinstance(r["position"], (int, float)) else "-"
            print(f"    {r['impressions']:>8,} impr  pos {pos:>5}  {r['url']}")

    print(sep)
