"""
auth.py — Autenticação com o Google Search Console via OAuth2 (conta do usuário).

Na primeira execução abre o navegador para login. O token é salvo em token.json
e reutilizado automaticamente nas execuções seguintes (com refresh automático).

Pré-requisito: client_secrets.json na raiz do projeto.
Obtido em: Google Cloud Console → APIs e Serviços → Credenciais →
           Criar credencial → ID do cliente OAuth2 → Aplicativo de desktop.
"""

import os
from datetime import UTC, datetime

from config import BASE_DIR
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


# Credenciais já carregadas nesta execução. Existe para que load_credentials()
# possa ser chamada por quem precisa do objeto Credentials (o inspector
# paralelo, que monta um Http por thread) sem disparar um segundo fluxo OAuth.
_CREDENTIALS = None


def load_credentials():
    """
    Retorna o objeto Credentials autenticado, reaproveitando o desta execução.

    É o mesmo fluxo de build_service() — apenas exposto separadamente porque o
    inspector paralelo precisa das credenciais para construir um httplib2.Http
    por thread (o Http interno do service NÃO é thread-safe).

    Levanta FileNotFoundError se client_secrets.json não for encontrado.
    """
    global _CREDENTIALS

    if _CREDENTIALS is not None and _CREDENTIALS.valid:
        return _CREDENTIALS

    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError(
            f"client_secrets.json não encontrado em: {CLIENT_SECRETS_FILE}\n"
            "Baixe as credenciais OAuth2 no Google Cloud Console:\n"
            "  APIs e Serviços → Credenciais → Criar credencial\n"
            "  → ID do cliente OAuth2 → Aplicativo de desktop\n"
            "Renomeie o arquivo baixado para client_secrets.json e coloque na raiz do projeto."
        )

    creds = None

    # Tenta carregar token salvo de execução anterior
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Se não há credenciais válidas, inicia o fluxo de login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[auth] Renovando token de acesso...")
            creds.refresh(Request())
        else:
            print("[auth] Abrindo navegador para autenticação no Google...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Salva o token para as próximas execuções
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"[auth] Token salvo em: {TOKEN_FILE}")

    _CREDENTIALS = creds
    return creds


def refresh_if_needed(credentials, margin_seconds: int = 600) -> None:
    """
    Renova o token se ele expira dentro de `margin_seconds`.

    Chamada ANTES de abrir um pool de threads: google-auth não serializa o
    refresh, então várias threads renovando o mesmo Credentials ao mesmo tempo
    é uma corrida. Renovando na mão antes, o pool inteiro roda com um token que
    não vai expirar no meio do caminho.
    """
    if credentials is None:
        return
    expiry = getattr(credentials, "expiry", None)
    if expiry is None:
        return
    # credentials.expiry é naive em UTC (convenção do google-auth).
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    restante = (expiry - datetime.now(UTC)).total_seconds()
    if restante > margin_seconds:
        return
    refresh_token = getattr(credentials, "refresh_token", None)
    if not refresh_token:
        return
    print("[auth] Renovando token antes de abrir o pool de threads...")
    credentials.refresh(Request())
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())


def build_service():
    """
    Autentica via OAuth2 e retorna o objeto de serviço da Search Console API.

    - Primeira execução: abre o navegador para o usuário fazer login.
    - Execuções seguintes: usa o token salvo em token.json (refresh automático).

    Levanta FileNotFoundError se client_secrets.json não for encontrado.

    O objeto devolvido NÃO é thread-safe (o httplib2.Http interno é
    compartilhado). Para uso concorrente, veja fetchers/inspector.py, que monta
    um Http por thread a partir de load_credentials().
    """
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError(
            f"client_secrets.json não encontrado em: {CLIENT_SECRETS_FILE}\n"
            "Baixe as credenciais OAuth2 no Google Cloud Console:\n"
            "  APIs e Serviços → Credenciais → Criar credencial\n"
            "  → ID do cliente OAuth2 → Aplicativo de desktop\n"
            "Renomeie o arquivo baixado para client_secrets.json e coloque na raiz do projeto."
        )

    creds = None

    # Tenta carregar token salvo de execução anterior
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Se não há credenciais válidas, inicia o fluxo de login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[auth] Renovando token de acesso...")
            creds.refresh(Request())
        else:
            print("[auth] Abrindo navegador para autenticação no Google...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Salva o token para as próximas execuções
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"[auth] Token salvo em: {TOKEN_FILE}")

    # Guarda para load_credentials() — evita um segundo fluxo OAuth quando o
    # inspector paralelo pedir as credenciais depois.
    global _CREDENTIALS
    _CREDENTIALS = creds

    service = build("searchconsole", "v1", credentials=creds)
    return service
