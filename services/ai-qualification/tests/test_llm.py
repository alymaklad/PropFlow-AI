import json

import httpx
import pytest

from app.llm import EMPTY_EXTRACTION, FakeLLM, GroqClient, LLMBadOutput, LLMUnavailable

SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def make(responses, **kwargs):
    requests, sleeps = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = GroqClient("key", "openai/gpt-oss-120b", transport=httpx.MockTransport(handler),
                        sleep=sleeps.append, **kwargs)
    return client, requests, sleeps


def completion(content, model="openai/gpt-oss-120b"):
    return httpx.Response(200, json={"model": model, "usage": {"total_tokens": 5},
                                     "choices": [{"message": {"content": content}}]})


def call(client):
    return client.complete_json(system="sys", user="usr", schema=SCHEMA, schema_name="s")


def test_request_uses_strict_json_schema():
    client, requests, _ = make([completion('{"a": 1}')], reasoning_effort="low")
    result = call(client)
    assert result.content == '{"a": 1}' and result.usage == {"total_tokens": 5}
    body = requests[0]
    assert body["model"] == "openai/gpt-oss-120b" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "s", "strict": True, "schema": SCHEMA}}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["reasoning_effort"] == "low"


def test_rate_limit_honours_retry_after_then_succeeds():
    client, requests, sleeps = make([
        httpx.Response(429, headers={"retry-after": "2"}), completion("{}")])
    assert call(client).content == "{}"
    assert sleeps == [2.0] and len(requests) == 2


def test_retry_after_is_capped():
    client, _, sleeps = make([httpx.Response(429, headers={"retry-after": "120"}),
                              completion("{}")])
    call(client)
    assert sleeps == [10.0]


def test_outage_gives_up_as_unavailable():
    client, requests, _ = make([httpx.ConnectError("down"), httpx.Response(503),
                                httpx.ReadTimeout("slow")])
    with pytest.raises(LLMUnavailable):
        call(client)
    assert len(requests) == 3


@pytest.mark.parametrize("status", [401, 403])
def test_bad_credentials_are_not_retried(status):
    client, requests, _ = make([httpx.Response(status)])
    with pytest.raises(LLMUnavailable, match="credentials"):
        call(client)
    assert len(requests) == 1


def test_schema_rejection_is_bad_output():
    client, _, _ = make([httpx.Response(400, json={"error": {"code": "json_validate_failed"}})])
    with pytest.raises(LLMBadOutput):
        call(client)


@pytest.mark.parametrize("response", [
    completion(""), httpx.Response(200, json={"choices": []}), httpx.Response(200, text="x")])
def test_unusable_success_responses(response):
    client, _, _ = make([response])
    with pytest.raises(LLMBadOutput):
        call(client)


def test_missing_key_is_unavailable():
    with pytest.raises(LLMUnavailable):
        GroqClient("", "model")


def test_fake_llm_script_and_default():
    fake = FakeLLM(script=[{"x": 1}, "raw", LLMUnavailable("down")])
    assert call(fake).content == '{"x": 1}'
    assert call(fake).content == "raw"
    with pytest.raises(LLMUnavailable):
        call(fake)
    assert json.loads(call(fake).content) == EMPTY_EXTRACTION
    assert len(fake.calls) == 4
