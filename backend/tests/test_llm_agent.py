import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agents import llm_agent
from app.agents.llm_agent import LLMAgent


def _agent(model):
    cfg = SimpleNamespace(groq_api_key="k", openai_api_key="", groq_model=model)
    with patch.object(llm_agent, "settings", cfg), patch.object(llm_agent, "OpenAI", MagicMock()):
        return LLMAgent()


def _reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_uses_configured_groq_model():
    assert _agent("openai/gpt-oss-120b").model == "openai/gpt-oss-120b"


def test_gpt_oss_requests_low_reasoning_and_room_for_answer():
    agent = _agent("openai/gpt-oss-120b")
    agent.client.chat.completions.create.return_value = _reply("Great mix tonight.")
    out = asyncio.run(agent.summarize_party_taste([], []))
    kwargs = agent.client.chat.completions.create.call_args.kwargs
    assert out == "Great mix tonight."
    assert kwargs["extra_body"] == {"reasoning_effort": "low"}
    assert kwargs["max_tokens"] >= 800


def test_other_models_send_no_reasoning_param():
    agent = _agent("llama-3.1-8b-instant")
    agent.client.chat.completions.create.return_value = _reply("ok")
    asyncio.run(agent.summarize_party_taste([], []))
    assert agent.client.chat.completions.create.call_args.kwargs["extra_body"] is None


def test_falls_back_when_call_fails():
    agent = _agent("openai/gpt-oss-120b")
    agent.client.chat.completions.create.side_effect = RuntimeError("model_decommissioned")
    assert asyncio.run(agent.summarize_party_taste([], [])).startswith("Party of 0 guests")
