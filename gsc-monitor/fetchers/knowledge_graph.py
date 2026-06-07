"""
knowledge_graph.py — Consulta a Knowledge Graph Search API do Google.

Verifica se o domínio/marca possui entidade registrada no Knowledge Graph.
Não requer OAuth — apenas uma API key do Google Cloud.

Como obter a API key:
  1. console.cloud.google.com → Ativar "Knowledge Graph Search API"
  2. APIs & Services → Credentials → Create API Key
  Guarde em: variável de ambiente GOOGLE_API_KEY
          ou arquivo: gsc-monitor/google_api_key.txt
"""

import json
import os
import requests
from datetime import datetime, timedelta
from config import BASE_DIR


KG_API_URL   = "https://kgsearch.googleapis.com/v1/entities:search"
TTL_KG_HOURS = 168   # 7 dias — entidades mudam raramente


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def load_api_key() -> "str | None":
    """Carrega a API key de: env var GOOGLE_API_KEY → arquivo google_api_key.txt."""
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if key:
        return key
    key_file = os.path.join(BASE_DIR, "google_api_key.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            pass
    return None


def save_api_key(key: str) -> None:
    """Persiste a API key no arquivo google_api_key.txt."""
    key_file = os.path.join(BASE_DIR, "google_api_key.txt")
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key.strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def brand_from_domain(domain: str) -> str:
    """Extrai o nome da marca (ex: www.exemplo.com.br → Exemplo)."""
    name = domain.removeprefix("www.").removeprefix("sc-domain:")
    return name.split(".")[0].replace("-", " ").replace("_", " ").title()


def _is_plausible_match(brand: str, entity_name: str, entity_url: str, domain: str) -> bool:
    """
    Heurística para detectar falsos positivos do Knowledge Graph.

    Problema: marcas curtas ou ambíguas (ex: "Bit") retornam entidades globais
    famosas (ex: "Bitcoin") que têm score altíssimo mas nada a ver com o domínio.

    Regras (em ordem — retorna True ao primeiro que passa):
      1. Nome idêntico após normalização                       → válido
      2. Sobreposição de nome com ratio adequado:
           - marcas ≤ 4 chars precisam de ratio ≥ 90 % (alta ambiguidade)
           - marcas > 4 chars precisam de ratio ≥ 70 %
      3. Primeiro segmento do domínio da entidade == primeiro
         segmento do domínio buscado (ex: bit.eng.br vs bitcoin.org → "bit"≠"bitcoin")

    Se nenhuma regra passar → falso positivo provável → retorna False.
    """
    b = brand.lower().replace(" ", "").replace("-", "")
    n = entity_name.lower().replace(" ", "").replace("-", "")

    # Regra 1: nome exato
    if b == n:
        return True

    # Regra 2: sobreposição de nome com threshold adaptativo
    if b in n or n in b:
        ratio = min(len(b), len(n)) / max(len(b), len(n))
        threshold = 0.90 if len(b) <= 4 else 0.70
        if ratio >= threshold:
            return True

    # Regra 3: primeiro segmento do domínio da entidade
    if entity_url:
        try:
            from urllib.parse import urlparse
            ent_first = (
                urlparse(entity_url).netloc
                .lower().removeprefix("www.").split(".")[0]
            )
            dom_first = domain.lower().removeprefix("www.").split(".")[0]
            if ent_first == dom_first:
                return True
        except Exception:
            pass

    return False


def _kg_cache_path(domain: str) -> str:
    from core.cache import _cache_dir
    # Usa o domínio completo (ex: "www.exemplo.com") para alinhar
    # com os demais caches do domínio (relatorios/{domain}/.cache/)
    return os.path.join(_cache_dir(domain), "knowledge_graph.json")


def _read_kg_cache(domain: str) -> "dict | None":
    path = _kg_cache_path(domain)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        cached_at = datetime.fromisoformat(entry.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_at) <= timedelta(hours=TTL_KG_HOURS):
            return entry.get("data")
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return None


def _write_kg_cache(domain: str, data: dict) -> None:
    path = _kg_cache_path(domain)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"cached_at": datetime.now().isoformat(timespec="seconds"), "data": data},
                f, ensure_ascii=False, indent=2,
            )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Consulta principal
# ---------------------------------------------------------------------------

def search_entity(
    domain: str,
    api_key: "str | None" = None,
    use_cache: bool = True,
) -> "dict | None":
    """
    Busca entidade da marca no Knowledge Graph do Google.

    Retorna dict com os dados da entidade, ou None se API key ausente.

    {
        "found":         bool,
        "brand":         str,      # nome buscado
        "name":          str,      # nome registrado no KG
        "types":         list[str],
        "description":   str,
        "detailed_desc": str,
        "kg_id":         str,
        "score":         float,
        "url":           str,
    }
    """
    if api_key is None:
        api_key = load_api_key()
    if not api_key:
        print("[knowledge_graph] API key não configurada — consulta KG ignorada.")
        print("[knowledge_graph] Configure GOOGLE_API_KEY ou crie google_api_key.txt.")
        return None

    # 'clean' é usado apenas como termo de busca (sem www/sc-domain).
    # O cache usa o 'domain' completo para ficar no diretório correto.
    clean = domain.removeprefix("www.").removeprefix("sc-domain:")

    if use_cache:
        cached = _read_kg_cache(domain)
        if cached is not None:
            if not cached.get("found"):
                # Cache: marca não encontrada → suprime a seção nos relatórios
                return None
            print("[knowledge_graph] [CACHE] Entidade carregada do cache.")
            return cached

    brand = brand_from_domain(domain)
    print(f"[knowledge_graph] Buscando entidade '{brand}' no Knowledge Graph...")

    try:
        resp = requests.get(
            KG_API_URL,
            params={"query": brand, "key": api_key, "limit": 3},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[knowledge_graph] ERRO na requisição: {exc}")
        return None

    items = resp.json().get("itemListElement", [])
    if not items:
        print(f"[knowledge_graph] '{brand}' não encontrada no Knowledge Graph do Google.")
        print("[knowledge_graph] Dica: Google Business Profile e Schema.org (Organization)")
        print("[knowledge_graph]       são os principais caminhos para aparecer no KG.")
        # Cacheia por 7 dias para evitar re-consulta; suprime seção retornando None
        if use_cache:
            _write_kg_cache(domain, {"found": False, "brand": brand})
        return None

    best        = max(items, key=lambda x: x.get("resultScore", 0))
    entity      = best.get("result", {})
    entity_name = entity.get("name", brand)
    entity_url  = entity.get("url", "")

    # Valida se o resultado realmente corresponde à marca buscada.
    # Marcas curtas/ambíguas (ex: "Pix") podem retornar entidades globais
    # famosas (ex: "Pixiv") com score altíssimo mas sem relação com o domínio.
    if not _is_plausible_match(brand, entity_name, entity_url, domain):
        print(f"[knowledge_graph] '{brand}' → resultado '{entity_name}' descartado "
              f"(falso positivo detectado — entidade não corresponde ao domínio).")
        print("[knowledge_graph] Dica: Google Business Profile e Schema.org (Organization)")
        print("[knowledge_graph]       são os principais caminhos para aparecer no KG.")
        if use_cache:
            _write_kg_cache(domain, {"found": False, "brand": brand})
        return None

    result = {
        "found":        True,
        "brand":        brand,
        "name":         entity_name,
        "types":        entity.get("@type", []),
        "description":  entity.get("description", ""),
        "detailed_desc": entity.get("detailedDescription", {}).get("articleBody", ""),
        "kg_id":        entity.get("@id", ""),
        "score":        round(best.get("resultScore", 0), 1),
        "url":          entity_url,
    }
    if use_cache:
        _write_kg_cache(domain, result)
    return result


def print_kg_result(result: "dict | None") -> None:
    """Exibe resultado do Knowledge Graph no terminal."""
    if result is None:
        return
    print(f"\n{'─' * 55}")
    print("  Knowledge Graph")
    print(f"{'─' * 55}")
    if not result.get("found"):
        print(f"  [{result.get('brand', '')}] Marca não encontrada no Knowledge Graph.")
    else:
        print(f"  Nome       : {result['name']}")
        types = ", ".join(t for t in result.get("types", []) if t != "Thing")
        if types:
            print(f"  Tipo(s)    : {types}")
        if result.get("description"):
            print(f"  Descrição  : {result['description']}")
        if result.get("detailed_desc"):
            desc = result["detailed_desc"]
            print(f"  Detalhe    : {desc[:180]}{'...' if len(desc) > 180 else ''}")
        print(f"  Score KG   : {result.get('score', 0):.1f}")
    print(f"{'─' * 55}\n")
