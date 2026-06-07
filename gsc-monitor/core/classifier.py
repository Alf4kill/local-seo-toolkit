"""
classifier.py — Mapeia o verdict da URL Inspection API para a categoria interna.
"""

# Mapeamento conforme especificação do projeto
VERDICT_MAP: dict[str, str] = {
    "PASS": "indexed",
    "FAIL": "not_indexed",
    "NEUTRAL": "warning",
    "VERDICT_UNSPECIFIED": "unknown",
}


def classify(verdict: str) -> str:
    """
    Recebe o valor de inspectionResult.indexStatusResult.verdict
    e retorna a categoria interna correspondente.
    Valores não mapeados são tratados como 'unknown'.
    """
    return VERDICT_MAP.get(verdict, "unknown")
