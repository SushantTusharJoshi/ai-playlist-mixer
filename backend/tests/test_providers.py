"""PM-F6 provider order and the Bedrock Converse provider (stubbed), PM-N8 no AWS needed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.llm import providers as prov
from app.llm.providers import BedrockProvider, Completion, build_providers

BACKEND = Path(__file__).resolve().parents[1]


def _cfg(**kw):
    base = dict(groq_api_key="", groq_model="openai/gpt-oss-120b", openai_api_key="", openai_model="gpt-4o-mini",
                bedrock_model_id="", aws_region="", llm_provider="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture()
def fake_openai(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", MagicMock())


@pytest.fixture()
def fake_boto3(monkeypatch):
    """A stand-in boto3 module: credentials present, client records the Converse call."""
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "Bedrock DJ: "}, {"text": "fair mix."}]}},
        "usage": {"inputTokens": 120, "outputTokens": 9, "totalTokens": 129},
        "metrics": {"latencyMs": 412},
        "stopReason": "end_turn",
    }
    mod = types.ModuleType("boto3")
    mod.client = MagicMock(return_value=client)
    mod.Session = MagicMock(return_value=SimpleNamespace(get_credentials=lambda: object()))
    monkeypatch.setitem(sys.modules, "boto3", mod)
    return mod, client


def test_no_keys_means_no_providers():
    assert build_providers(_cfg()) == []


def test_order_is_groq_then_openai_then_bedrock(fake_openai, fake_boto3):
    names = [p.name for p in build_providers(_cfg(groq_api_key="g", openai_api_key="o",
                                                  bedrock_model_id="amazon.nova-lite-v1:0"))]
    assert names == ["groq", "openai", "bedrock"]


def test_bedrock_only_when_selected(fake_openai, fake_boto3):
    picked = build_providers(_cfg(groq_api_key="g", openai_api_key="o", bedrock_model_id="m", llm_provider="bedrock"))
    assert [p.name for p in picked] == ["bedrock"]


def test_bedrock_off_without_model_id(fake_boto3):
    mod, _ = fake_boto3
    assert build_providers(_cfg()) == []
    mod.client.assert_not_called()


def test_bedrock_off_without_credentials(fake_boto3):
    mod, _ = fake_boto3
    mod.Session = MagicMock(return_value=SimpleNamespace(get_credentials=lambda: None))
    assert build_providers(_cfg(bedrock_model_id="m")) == []


def test_bedrock_off_when_boto3_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # import boto3 raises ImportError
    assert build_providers(_cfg(bedrock_model_id="m")) == []


def test_bedrock_converse_request_and_completion(fake_boto3):
    mod, client = fake_boto3
    p = BedrockProvider("amazon.nova-lite-v1:0", region="us-east-1")
    mod.client.assert_called_once_with("bedrock-runtime", region_name="us-east-1")
    c = p.complete("room data", system="rules", max_tokens=300, temperature=0.5)
    client.converse.assert_called_once_with(
        modelId="amazon.nova-lite-v1:0",
        messages=[{"role": "user", "content": [{"text": "room data"}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0.5},
        system=[{"text": "rules"}],
    )
    assert c == Completion(text="Bedrock DJ: fair mix.", model="amazon.nova-lite-v1:0", provider="bedrock",
                           input_tokens=120, output_tokens=9, latency_ms=412.0, cached=False)


def test_bedrock_without_system_sends_no_system_block(fake_boto3):
    _, client = fake_boto3
    BedrockProvider("m").complete("hi")
    assert "system" not in client.converse.call_args.kwargs


def test_openai_compat_completion_fields():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hey"))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=3))
    c = prov.OpenAICompatProvider("groq", "k", "llama", client=client).complete("p", system="s")
    assert (c.text, c.provider, c.input_tokens, c.output_tokens, c.cached) == ("hey", "groq", 50, 3, False)
    assert client.chat.completions.create.call_args.kwargs["messages"][0] == {"role": "system", "content": "s"}


NO_AWS_SCRIPT = """
import json, sys
from fastapi.testclient import TestClient
from app.main import app, llm_agent
from app.data import PARTIES
with TestClient(app) as c:
    code = c.post("/party/create", json={}).json()["code"]
    c.post(f"/party/{code}/join", json={"display_name": "Ann", "genre": "pop"})
    r = c.post(f"/party/{code}/generate-queue", headers={"X-Host-Key": PARTIES[code].host_key})
    print(json.dumps({"status": r.status_code, "summary": r.json()["ai_summary"],
                      "providers": [p.name for p in llm_agent.providers], "boto3": "boto3" in sys.modules}))
"""


def test_app_runs_with_no_aws_keys(tmp_path):
    """PM-N8: a fresh process with no AWS or LLM settings starts, generates a queue and a summary."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "BEDROCK_", "GROQ_", "OPENAI_"))}
    env["ROOM_STATE_PATH"] = str(tmp_path / "rooms.json")
    out = subprocess.run([sys.executable, "-c", NO_AWS_SCRIPT], cwd=BACKEND, env=env, capture_output=True,
                         text=True, timeout=60, check=True)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["status"] == 200
    assert result["providers"] == []
    assert result["summary"].startswith("Party of 1 guests")
    assert result["boto3"] is False
