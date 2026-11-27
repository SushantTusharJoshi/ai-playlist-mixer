"""
LLM providers behind one small interface.

Every provider has `complete(prompt, *, system=None, max_tokens=512,
temperature=0.0) -> Completion`. The party summary tries them in order:
Groq, then OpenAI, then Amazon Bedrock (Converse API). Each one is on only when
its settings are present. Set LLM_PROVIDER to use exactly one of them.

boto3 is imported only when BEDROCK_MODEL_ID is set, so the app runs (and its
tests pass) with no AWS packages or credentials.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False


class Provider(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 512,
                 temperature: float = 0.0) -> Completion: ...


class OpenAICompatProvider:
    """Groq and OpenAI both speak the OpenAI chat completions API."""

    def __init__(self, name: str, api_key: str, model: str, base_url: str | None = None, client=None):
        self.name = name
        self.model = model
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.client = client

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 512,
                 temperature: float = 0.0) -> Completion:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        start = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature, messages=messages,
            # gpt-oss models reason before answering; reasoning tokens count toward max_tokens
            extra_body={"reasoning_effort": "low"} if "gpt-oss" in self.model else None,
        )
        usage = getattr(resp, "usage", None)
        return Completion(
            text=resp.choices[0].message.content or "",
            model=self.model, provider=self.name,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )


class BedrockProvider:
    """Amazon Bedrock through the Converse API. Not exercised against live AWS yet."""

    name = "bedrock"

    def __init__(self, model_id: str, region: str | None = None, client=None):
        self.model = model_id
        if client is None:
            import boto3  # lazy: only when Bedrock is turned on
            client = boto3.client("bedrock-runtime", region_name=region) if region else boto3.client("bedrock-runtime")
        self.client = client

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 512,
                 temperature: float = 0.0) -> Completion:
        kwargs = {
            "modelId": self.model,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        start = time.perf_counter()
        resp = self.client.converse(**kwargs)
        parts = resp.get("output", {}).get("message", {}).get("content", [])
        usage = resp.get("usage", {})
        return Completion(
            text="".join(p.get("text", "") for p in parts),
            model=self.model, provider=self.name,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            latency_ms=float(resp.get("metrics", {}).get("latencyMs", round((time.perf_counter() - start) * 1000, 1))),
        )


def _aws_credentials_present() -> bool:
    try:
        import boto3
    except ImportError:
        print("BEDROCK_MODEL_ID is set but boto3 is not installed (pip install -r requirements-bedrock.txt)")
        return False
    return boto3.Session().get_credentials() is not None


def build_providers(settings) -> list[Provider]:
    """Providers in fallback order, from whatever keys are configured."""
    only = (getattr(settings, "llm_provider", "") or "").strip().lower()
    providers: list[Provider] = []

    def wanted(name: str) -> bool:
        return not only or only == name

    if wanted("groq") and getattr(settings, "groq_api_key", ""):
        providers.append(OpenAICompatProvider("groq", settings.groq_api_key, settings.groq_model,
                                              base_url="https://api.groq.com/openai/v1"))
    if wanted("openai") and getattr(settings, "openai_api_key", ""):
        providers.append(OpenAICompatProvider("openai", settings.openai_api_key,
                                              getattr(settings, "openai_model", "") or "gpt-4o-mini"))
    model_id = getattr(settings, "bedrock_model_id", "")
    if wanted("bedrock") and model_id and _aws_credentials_present():
        providers.append(BedrockProvider(model_id, getattr(settings, "aws_region", "") or None))
    return providers
