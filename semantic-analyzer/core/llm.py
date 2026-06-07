"""
llm.py — Cliente para um LLM LOCAL (sem API paga).

Dois backends, mesma interface .chat(system, user) -> str:
  - LLMClient        : API compatível com OpenAI (Ollama localhost:11434/v1,
                       LM Studio localhost:1234/v1). Roda na GPU da máquina
                       (RX 6750XT via Vulkan). RECOMENDADO p/ qualidade.
  - TransformersClient: modelo local via transformers em CPU. Sem servidor,
                       porém lento — use modelo pequeno. Bom p/ teste/fallback.

Mais: parser robusto de JSON (modelos costumam embrulhar em ```json``` ou texto).
"""

import json
import re

import requests

OLLAMA_URL = "http://localhost:11434/v1"
LMSTUDIO_URL = "http://localhost:1234/v1"
DEFAULT_URL = OLLAMA_URL
DEFAULT_MODEL = "qwen2.5:7b-instruct"  # exemplo — ajuste ao que você baixou


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    """LLM local via endpoint compatível com OpenAI (Ollama / LM Studio)."""

    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, timeout: int = 180):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            return requests.get(self.url + "/models", timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def chat(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 700) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(self.url + "/chat/completions", json=payload, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Falha ao chamar LLM em {self.url}: {exc}") from exc
        return r.json()["choices"][0]["message"]["content"]

    def unload(self) -> bool:
        """
        Descarrega o modelo da memória AGORA (em vez de esperar o keep_alive do
        Ollama, ~5 min). Usa o endpoint nativo do Ollama com keep_alive=0.
        Best-effort: retorna False (sem erro) em servidores que não sejam Ollama
        (ex.: LM Studio não tem esse endpoint).
        """
        base = re.sub(r"/v1/?$", "", self.url)
        try:
            r = requests.post(
                base + "/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=10
            )
            return r.status_code == 200
        except requests.RequestException:
            return False


class TransformersClient:
    """
    LLM local via transformers (CPU). Sem servidor externo. LENTO — use modelo
    pequeno (ex.: Qwen2.5-0.5B/1.5B-Instruct). Útil p/ teste e fallback.
    """

    def __init__(self, model: str = "Qwen/Qwen2.5-0.5B-Instruct", max_tokens: int = 500):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self.tok = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForCausalLM.from_pretrained(model)  # CPU float32 por padrão
        self.max_tokens = max_tokens

    def available(self) -> bool:
        return True

    def unload(self) -> bool:
        """No-op: o modelo vive no próprio processo e é liberado quando o script sai."""
        return False

    def chat(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = None) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        inputs = self.tok.apply_chat_template(
            msgs,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
        with self._torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens or self.max_tokens,
                do_sample=False,
                pad_token_id=self.tok.eos_token_id,
            )
        gen = out[0][inputs["input_ids"].shape[1] :]
        return self.tok.decode(gen, skip_special_tokens=True)


def parse_json_block(text: str) -> dict:
    """
    Extrai o primeiro objeto JSON de um texto, tolerando ```json``` , ruído antes/
    depois e vírgulas finais. Retorna {} se não houver JSON aproveitável.
    """
    if not text:
        return {}
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j == -1 or j < i:
        return {}
    snippet = text[i : j + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        snippet = re.sub(r",\s*([}\]])", r"\1", snippet)  # remove vírgulas finais
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return {}
