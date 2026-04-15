"""Generation pipeline.

Supports two backends (chosen automatically from .env):

1. Hugging Face Inference Providers (via `huggingface_hub.AsyncInferenceClient`).
   Set `HUGGINGFACEHUB_API_TOKEN` and optionally `HF_PROVIDER`.
2. Any OpenAI-compatible endpoint (Groq, OpenRouter, local llama.cpp, Ollama, OpenAI).
   Set `LLM_BASE_URL` (e.g. `https://api.groq.com/openai/v1`) and `LLM_API_KEY`.

If both are set, the OpenAI-compatible endpoint takes precedence — useful because
many Hugging Face free serverless models have been deprecated (HTTP 410).
"""
import os
from typing import AsyncIterator

from src.config import settings
from src.core.prompts import (
    HYDE_PROMPT,
    SUGGESTED_QUESTIONS_PROMPT,
    SYSTEM_PROMPT,
    build_context_block,
    build_user_prompt,
)
from src.core.schemas import ChatMessage, RetrievedChunk


# ── backend selection ───────────────────────────────────────────────────────

def _use_openai_compatible() -> bool:
    return bool(os.environ.get("LLM_BASE_URL"))


_hf_client = None
_openai_client = None


def _get_hf_client():
    global _hf_client
    if _hf_client is None:
        from huggingface_hub import AsyncInferenceClient

        provider = os.environ.get("HF_PROVIDER", "auto")  # "auto" lets HF route
        token = settings.HUGGINGFACEHUB_API_TOKEN or None
        _hf_client = AsyncInferenceClient(provider=provider, token=token, timeout=120)
    return _hf_client


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError(
                "OpenAI-compatible backend requested but the `openai` package is not installed. "
                "Run: pip install openai"
            ) from e

        base_url = os.environ.get("LLM_BASE_URL")
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "not-needed"
        _openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    return _openai_client


def _model() -> str:
    # When an OpenAI-compatible endpoint is used, LLM_MODEL wins; otherwise HF model.
    return os.environ.get("LLM_MODEL") or settings.HF_CHAT_MODEL


# ── message helpers ─────────────────────────────────────────────────────────

def _messages(system: str, user: str, history: list[ChatMessage] | None = None) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": system}]
    for m in (history or [])[-6:]:
        if m.role in {"user", "assistant"} and m.content:
            msgs.append({"role": m.role, "content": m.content})
    msgs.append({"role": "user", "content": user})
    return msgs


# ── streaming chat ──────────────────────────────────────────────────────────

def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


async def _openai_stream(client, model, messages, max_tokens, temperature):
    """Handle models that require ``max_completion_tokens`` (o1/gpt-5) transparently.

    Reasoning models (gpt-5/o1/o3) consume tokens on internal reasoning BEFORE
    emitting visible content. If ``max_completion_tokens`` is too small, the
    stream finishes empty — user sees sources but no answer. Bump the budget
    and lower ``reasoning_effort`` to ``minimal`` so most tokens go to output.
    """
    if _is_reasoning_model(model):
        budget = max(max_tokens, 4096)
        try:
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                max_completion_tokens=budget,
                reasoning_effort="minimal",
            )
        except Exception:
            # Older SDKs may not accept reasoning_effort — retry without it.
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                max_completion_tokens=budget,
            )

    # Classic chat models (gpt-4o, gpt-4o-mini, gpt-3.5, Groq, etc.)
    try:
        return await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        if "max_completion_tokens" in str(e) or "Unsupported parameter: 'max_tokens'" in str(e):
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                max_completion_tokens=max(max_tokens, 4096),
            )
        raise


async def _stream_chat(messages: list[dict], max_tokens: int, temperature: float) -> AsyncIterator[str]:
    model = _model()
    if _use_openai_compatible():
        client = _get_openai_client()
        stream = await _openai_stream(client, model, messages, max_tokens, temperature)
        async for event in stream:
            try:
                delta = event.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                yield delta
        return

    client = _get_hf_client()
    stream = await client.chat_completion(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    async for event in stream:
        try:
            delta = event.choices[0].delta.content
        except Exception:
            delta = None
        if delta:
            yield delta


async def _complete_chat(messages: list[dict], max_tokens: int, temperature: float) -> str:
    model = _model()
    if _use_openai_compatible():
        client = _get_openai_client()
        if _is_reasoning_model(model):
            budget = max(max_tokens, 4096)
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=budget,
                    reasoning_effort="minimal",
                )
            except Exception:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_completion_tokens=budget,
                )
        else:
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                if "max_completion_tokens" in str(e) or "Unsupported parameter: 'max_tokens'" in str(e):
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_completion_tokens=max(max_tokens, 4096),
                    )
                else:
                    raise
        return (resp.choices[0].message.content or "").strip()

    client = _get_hf_client()
    resp = await client.chat_completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


# ── public API ──────────────────────────────────────────────────────────────

async def stream_answer(
    query: str,
    chunks: list[RetrievedChunk],
    history: list[ChatMessage] | None = None,
) -> AsyncIterator[str]:
    """Yield answer tokens. If no chunks, refuse cleanly."""
    if not chunks:
        yield "I could not find this in the provided documents."
        return

    context = build_context_block(chunks)
    user_msg = build_user_prompt(query, context)
    messages = _messages(SYSTEM_PROMPT, user_msg, history)

    try:
        async for delta in _stream_chat(messages, settings.MAX_NEW_TOKENS, settings.TEMPERATURE):
            yield delta
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "410" in msg or "Gone" in msg:
            yield (
                "\n\n⚠️ The configured LLM endpoint has been deprecated by the provider (HTTP 410). "
                "Switch to a supported model or point `LLM_BASE_URL` at an OpenAI-compatible "
                "endpoint (Groq, OpenRouter, Ollama). See the README for details.\n\n"
                f"[debug] model={_model()}  error={msg}"
            )
        else:
            yield f"\n\n⚠️ Generation error: {msg}"


async def hyde_generate(query: str) -> str:
    messages = [{"role": "user", "content": HYDE_PROMPT.format(query=query)}]
    try:
        return await _complete_chat(messages, max_tokens=160, temperature=0.3)
    except Exception:
        return ""


async def generate_suggested_questions(excerpts: str) -> list[str]:
    messages = [{"role": "user", "content": SUGGESTED_QUESTIONS_PROMPT.format(excerpts=excerpts)}]
    try:
        text = await _complete_chat(messages, max_tokens=300, temperature=0.4)
    except Exception:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cleaned: list[str] = []
    for ln in lines:
        while ln and ln[0] in "0123456789.)-* ":
            ln = ln[1:].lstrip()
        if ln and ln.endswith("?"):
            cleaned.append(ln)
    return cleaned[:6]
