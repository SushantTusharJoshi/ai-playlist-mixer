"""Test doubles for LLM providers."""
from __future__ import annotations

from app.llm.providers import Completion


class StubProvider:
    """Returns a fixed reply (or one built from the prompt) and counts calls."""

    def __init__(self, reply="Two crews tonight: pop fans and rockers, and the queue takes turns.",
                 name="stub", fail=False):
        self.name = name
        self.model = f"{name}-model"
        self.reply = reply
        self.fail = fail
        self.calls = 0
        self.prompts: list[tuple[str | None, str]] = []

    def complete(self, prompt, *, system=None, max_tokens=512, temperature=0.0):
        self.calls += 1
        self.prompts.append((system, prompt))
        if self.fail:
            raise RuntimeError(f"{self.name} is down")
        text = self.reply(prompt) if callable(self.reply) else self.reply
        return Completion(text=text, model=self.model, provider=self.name, input_tokens=len(prompt) // 4,
                          output_tokens=len(text) // 4, latency_ms=1.0)
