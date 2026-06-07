"""
embedder.py — Transforma textos em embeddings (vetores de significado).

Backend principal: sentence-transformers (modelo multilíngue local, roda em CPU,
sem cota/custo). Import preguiçoso: o clusterer e os testes NÃO dependem dele.

Fallback opcional: TF-IDF (sklearn) — similaridade LÉXICA (palavras em comum),
NÃO semântica. Só para quando sentence-transformers não está disponível; avisa
claramente que o resultado não captura sinônimos/paráfrases.
"""

import hashlib
import os

import numpy as np

# Modelo pequeno, multilíngue (bom em PT), ~470MB no 1º uso. Roda em CPU.
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def embed_texts(texts: list, model_name: str = DEFAULT_MODEL, backend: str = "auto"):
    """
    Retorna (embeddings: np.ndarray, backend_usado: str).

    backend:
      "auto" — usa sentence-transformers se instalado; senão cai para TF-IDF.
      "st"   — exige sentence-transformers (levanta erro se ausente).
      "tfidf"— força TF-IDF (léxico).
    """
    if backend in ("auto", "st"):
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[embedder] Carregando modelo '{model_name}' (1ª vez baixa ~470MB)...")
            model = SentenceTransformer(model_name)
            emb = model.encode(
                texts, batch_size=32, show_progress_bar=True,
                convert_to_numpy=True, normalize_embeddings=True,
            )
            return emb, "sentence-transformers (semântico)"
        except ImportError:
            if backend == "st":
                raise ImportError(
                    "sentence-transformers não instalado. "
                    "Rode: pip install sentence-transformers"
                )
            print("[embedder] sentence-transformers ausente — usando TF-IDF (LÉXICO, não semântico).")

    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(max_features=8192, ngram_range=(1, 2))
    emb = vec.fit_transform(texts).toarray()
    return emb, "tf-idf (léxico — não semântico)"


# ---------------------------------------------------------------------------
# Cache de embeddings em disco (chaveado por modelo + conteúdo das páginas)
# ---------------------------------------------------------------------------

def _emb_cache_key(model: str, backend: str, labels: list, texts: list) -> str:
    h = hashlib.sha256()
    h.update(model.encode()); h.update(b"\x00")
    h.update(backend.encode()); h.update(b"\x00")
    for lab, txt in zip(labels, texts):
        h.update(lab.encode("utf-8", "ignore")); h.update(b"\x01")
        h.update(txt.encode("utf-8", "ignore")); h.update(b"\x02")
    return h.hexdigest()[:16]


def embed_texts_cached(labels, texts, model_name=None, backend="auto",
                       cache_dir=".cache", use_cache=True):
    """
    Como embed_texts, mas persiste os embeddings em disco. A chave inclui o
    modelo e o conteúdo de todas as páginas — se o conteúdo muda, o cache
    invalida sozinho. Retorna (emb, backend_usado, cache_hit: bool).
    """
    eff_model = model_name or DEFAULT_MODEL
    key  = _emb_cache_key(eff_model, backend, labels, texts)
    path = os.path.join(cache_dir, f"emb_{key}.npz")

    if use_cache and os.path.exists(path):
        data = np.load(path, allow_pickle=True)
        return data["emb"], str(data["backend"]), True

    kw = {"backend": backend}
    if model_name:
        kw["model_name"] = model_name
    emb, used = embed_texts(texts, **kw)

    if use_cache:
        os.makedirs(cache_dir, exist_ok=True)
        np.savez(path, emb=emb, backend=used, labels=np.array(labels, dtype=object))
    return emb, used, False
