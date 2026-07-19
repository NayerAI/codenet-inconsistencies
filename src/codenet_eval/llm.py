"""OpenRouter (OpenAI-compatible) chat client and response parsing."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .config import LLMConfig
from .utils import get_logger

log = get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    raw_content: str
    parsed: dict[str, Any]
    model: str
    usage: dict[str, Any]
    error: Optional[str] = None


class OpenRouterClient:
    """Minimal client for OpenRouter's ``/chat/completions`` endpoint.

    OpenRouter speaks the OpenAI chat API, so this also works against any
    OpenAI-compatible ``base_url`` by pointing ``llm.base_url`` elsewhere.
    """

    def __init__(self, cfg: LLMConfig, api_key: Optional[str] = None):
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else os.environ.get(cfg.api_key_env, "")
        if not self.api_key:
            raise LLMError(
                f"No API key found. Set the '{cfg.api_key_env}' environment variable."
            )
        self.endpoint = cfg.base_url.rstrip("/") + "/chat/completions"
        self.session = requests.Session()
        # Size the connection pool for concurrent evaluation workers so we don't
        # churn connections. requests.Session is safe to share across threads.
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=64)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.cfg.extra_headers or {})
        return headers

    def complete(
        self, messages: list[dict[str, str]], json_object: Optional[bool] = None
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        # json_object overrides cfg.json_mode (transpilation wants raw code, not JSON).
        want_json = self.cfg.json_mode if json_object is None else json_object
        if want_json:
            payload["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.cfg.request_timeout,
                )
            except requests.RequestException as exc:  # network error
                last_error = exc
                self._sleep(attempt, f"network error: {exc}")
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                self._sleep(attempt, f"retryable HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")

            data = resp.json()
            return self._parse_completion(data)

        raise LLMError(f"Exhausted {self.cfg.max_retries} retries; last error: {last_error}")

    def _sleep(self, attempt: int, reason: str) -> None:
        delay = self.cfg.retry_backoff ** attempt
        log.warning("LLM request attempt %d failed (%s); retrying in %.1fs", attempt, reason, delay)
        time.sleep(delay)

    def _parse_completion(self, data: dict[str, Any]) -> LLMResponse:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected completion shape: {json.dumps(data)[:400]}") from exc
        model = data.get("model", self.cfg.model)
        usage = data.get("usage", {}) or {}
        parsed, err = parse_json_object(content)
        return LLMResponse(raw_content=content, parsed=parsed, model=model, usage=usage, error=err)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(text: str) -> tuple[dict[str, Any], Optional[str]]:
    """Best-effort extraction of a single JSON object from model output.

    Returns ``(parsed, error)``.  On failure ``parsed`` is an empty dict and
    ``error`` describes what went wrong -- the caller records this rather than
    crashing the whole run over one malformed reply.
    """
    if not text or not text.strip():
        return {}, "empty response"

    candidates: list[str] = []
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    # Fall back to the substring between the first '{' and the last '}'.
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj, None
        except json.JSONDecodeError:
            continue
    return {}, "could not parse JSON object from response"
