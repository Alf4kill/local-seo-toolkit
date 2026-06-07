"""
auth.py — Autenticação com o Google Search Console via OAuth2 (conta do usuário).

Na primeira execução abre o navegador para login. O token é salvo em token.json
e reutilizado automaticamente nas execuções seguintes (com refresh automático).

Pré-requisito: client_secrets.json na raiz do projeto.
Obtido em: Google Cloud Console → APIs e Serviços → Credenciais →
           Criar credencial → ID do cliente OAuth2 → Aplicativo de desktop.
"""

import os
from config import BASE_DIR
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


def build_service():
    """
    Autentica via OAuth2 e retorna o objeto de serviço da Search Console API.

    - Primeira execução: abre o navegador para o usuário fazer login.
    - Execuções seguintes: usa o token salvo em token.json (refresh automático).

    Levanta FileNotFoundError se client_secrets.json não for encontrado.
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

    service = build("searchconsole", "v1", credentials=creds)
    return service
