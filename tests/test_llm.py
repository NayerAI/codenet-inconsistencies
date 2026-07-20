import pytest

from codenet_eval.config import LLMConfig
from codenet_eval.llm import LLMError, OpenRouterClient, parse_json_object


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _BadJsonResp:
    """A 200 whose body is not valid JSON (truncated/HTML/streamed)."""
    status_code = 200
    text = "<html>gateway error</html>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _ok_resp():
    content = '{"inconsistent": true}'
    return _FakeResp(200, {"model": "m", "choices": [{"message": {"content": content}}],
                           "usage": {"total_tokens": 3}})


def test_non_json_body_is_retried_then_recovers(monkeypatch):
    client = OpenRouterClient(LLMConfig(model="m", max_retries=3, json_mode=False), api_key="k")
    monkeypatch.setattr(client, "_sleep", lambda *a, **k: None)
    seq = iter([_BadJsonResp(), _BadJsonResp(), _ok_resp()])
    monkeypatch.setattr(client.session, "post", lambda *a, **k: next(seq))
    resp = client.complete([{"role": "user", "content": "x"}])
    assert resp.parsed == {"inconsistent": True}   # recovered on the 3rd attempt


def test_non_json_body_exhausts_retries_as_llm_error(monkeypatch):
    client = OpenRouterClient(LLMConfig(model="m", max_retries=2, json_mode=False), api_key="k")
    monkeypatch.setattr(client, "_sleep", lambda *a, **k: None)
    monkeypatch.setattr(client.session, "post", lambda *a, **k: _BadJsonResp())
    with pytest.raises(LLMError):        # not a raw JSONDecodeError
        client.complete([{"role": "user", "content": "x"}])


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMError):
        OpenRouterClient(LLMConfig(api_key_env="OPENROUTER_API_KEY"))


def test_client_builds_payload_and_parses(monkeypatch):
    cfg = LLMConfig(model="test/model", json_mode=True)
    client = OpenRouterClient(cfg, api_key="sk-test")

    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        content = '{"inconsistent": true, "divergence_input": "7 2"}'
        return _FakeResp(200, {"model": "test/model",
                               "choices": [{"message": {"content": content}}],
                               "usage": {"total_tokens": 11}})

    monkeypatch.setattr(client.session, "post", fake_post)
    resp = client.complete([{"role": "user", "content": "hi"}])

    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "test/model"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert resp.parsed["inconsistent"] is True
    assert resp.usage["total_tokens"] == 11
    assert resp.error is None


def test_parses_plain_json():
    obj, err = parse_json_object('{"inconsistent": true, "confidence": 0.9}')
    assert err is None
    assert obj["inconsistent"] is True


def test_parses_fenced_json():
    text = "Here you go:\n```json\n{\"inconsistent\": false}\n```\n"
    obj, err = parse_json_object(text)
    assert err is None
    assert obj["inconsistent"] is False


def test_parses_json_with_surrounding_prose():
    text = 'Sure. {"inconsistent": true, "divergence_input": "7 2"} Hope that helps.'
    obj, err = parse_json_object(text)
    assert err is None
    assert obj["divergence_input"] == "7 2"


def test_reports_error_on_garbage():
    obj, err = parse_json_object("no json here")
    assert obj == {}
    assert err is not None


def test_empty_response():
    obj, err = parse_json_object("")
    assert obj == {}
    assert err == "empty response"
