"""
llm_provider.py — thin wrapper over the Gemini API.

Reads GEMINI_API_KEY from the environment (loaded from .env by the caller).
The model is asked for a JSON object; this module returns the parsed dict
or raises. It makes NO judgment about whether the proposal is correct —
that is the validator's job.
"""

from __future__ import annotations

import json
import os
import time

from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

MODEL = "gemini-3.5-flash-lite"


class LLMError(RuntimeError):
    pass


import socket
import httpx
from google.genai import types

# TCP keepalive options to prevent NAT/firewall from silently dropping idle connections
_KEEPALIVE = [
    (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),    # first probe after 60s idle
    (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15),   # probe every 15s
    (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4),      # 4 failed probes = dead
]

_CLIENT: genai.Client | None = None

_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _call_with_timeout(fn, timeout_s: float = 45.0):
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout:
        raise LLMError(f"call exceeded {timeout_s}s wall clock")


def _client() -> genai.Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set")
    transport = httpx.HTTPTransport(socket_options=_KEEPALIVE)
    http_client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )
    _CLIENT = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            httpx_client=http_client,
            timeout=30_000,
        ),
    )
    return _CLIENT
def propose(prompt: str, retries: int = 3) -> dict:
    """
    Send `prompt`, expect a JSON object back, return it as a dict.
    Retries on transient errors (429 rate limit, 5xx).
    """
    client = _client()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            def _do_call():
                return client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                        thinking_config=types.ThinkingConfig(thinking_level="low"),
                    ),
                )

            resp = _call_with_timeout(_do_call, timeout_s=45.0)
            text = resp.text or ""
            data = json.loads(text)
            if isinstance(data, list):
                if not data:
                    raise LLMError("empty JSON array from model")
                data = data[0]
            if not isinstance(data, dict):
                raise LLMError(f"expected JSON object, got {type(data).__name__}")
            return data
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(2 ** attempt)
        except LLMError as e:
            last_err = e
            time.sleep(2 ** attempt)
        except Exception as e:  # noqa: BLE001 — retry on anything transient
            last_err = e
            time.sleep(2 ** attempt)
    raise LLMError(f"proposal failed after {retries} attempts: {last_err}")