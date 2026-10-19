import json

import httpx
import pytest
from openai import OpenAI

from scriptor.config import Settings
from scriptor.errors import ModelError
from scriptor.llm import ResponsesModel
from scriptor.models import Bible

from .conftest import bible


def response(text, status="completed", refusal=False):
    content = (
        [{"type": "refusal", "refusal": "declined"}]
        if refusal
        else [{"type": "output_text", "text": text, "annotations": []}]
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "test-model",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def provider(handler, structured=True):
    client = OpenAI(
        api_key="test-key",
        base_url="https://model.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return ResponsesModel(Settings(model="test-model", structured_output=structured), client=client)


def test_actual_sdk_sends_responses_json_schema_not_chat_completions():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=response(bible().model_dump_json()))

    model = provider(handler)
    assert model.structured("editor", "plan", Bible) == bible()
    request = captured[0]
    assert request.url.path == "/v1/responses"
    body = json.loads(request.content)
    assert "messages" not in body and "response_format" not in body
    assert body["input"][0]["content"][0] == {"type": "input_text", "text": "plan"}
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert model.calls[0]["usage"]["total_tokens"] == 30


def test_plain_text_and_explicit_json_compatibility_mode():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response(bible().model_dump_json()))

    model = provider(handler, structured=False)
    model.structured("editor", "plan", Bible)
    assert "text" not in captured[0]
    assert "Schema" in captured[0]["input"][0]["content"][0]["text"]


@pytest.mark.parametrize(
    "payload", [response("", refusal=True), response("partial", status="incomplete"), response("")]
)
def test_refusal_incomplete_and_empty_are_errors(payload):
    model = provider(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ModelError):
        model.text("writer", "write")


def test_invalid_json_is_not_silently_repaired():
    model = provider(lambda request: httpx.Response(200, json=response('{"world":"only"}')))
    with pytest.raises(ModelError, match="Bible"):
        model.structured("editor", "plan", Bible)


def test_provider_failure_has_no_chat_fallback_or_secret_body():
    captured = []

    def handler(request):
        captured.append(request.url.path)
        return httpx.Response(404, json={"error": {"message": "secret-provider-body"}})

    model = provider(handler)
    with pytest.raises(ModelError) as exc:
        model.text("writer", "write")
    assert "secret-provider-body" not in str(exc.value)
    assert captured == ["/v1/responses"]


def test_openai_503_is_also_background_retryable():
    from scriptor.errors import TransientModelError

    model = provider(lambda req: httpx.Response(503, json={"error": {"message": "private"}}))
    with pytest.raises(TransientModelError) as exc:
        model.text("writer", "write")
    assert "HTTP 503" in str(exc.value)
    assert "private" not in str(exc.value)
    assert model.calls[0]["provider"] == "openai"
