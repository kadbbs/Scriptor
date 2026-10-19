import json

import httpx
import pytest
from anthropic import Anthropic

from scriptor.config import Settings
from scriptor.errors import ModelError, StructuredOutputError
from scriptor.llm import AnthropicModel, ResponsesModel, create_model
from scriptor.models import Bible, LiteraryReview, NarrativeBrief, SourceReview

from .conftest import bible


def response(text, stop="end_turn", content=None):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-claude",
        "content": content if content is not None else [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5},
    }


def provider(handler, structured=True):
    client = Anthropic(
        api_key="test-anthropic-key",
        base_url="https://anthropic.invalid",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return AnthropicModel(
        Settings(provider="anthropic", model="test-claude", structured_output=structured), client
    )


def test_sdk_uses_messages_auth_system_and_transformed_schema():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=response(bible().model_dump_json()))

    with_model = provider(handler)
    assert with_model.structured("editor", "outline", Bible) == bible()
    req = captured[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == "test-anthropic-key"
    assert "anthropic-version" in req.headers
    assert body["system"] == "editor"
    assert body["messages"] == [{"role": "user", "content": "outline"}]
    assert body["max_tokens"] == 12000
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert '"minLength":' not in json.dumps(body["output_config"]["format"]["schema"])
    assert with_model.calls[0]["usage"]["total_tokens"] == 35
    with_model.close()


def test_text_joins_text_blocks_and_ignores_thinking():
    model = provider(
        lambda req: httpx.Response(
            200,
            json=response(
                "",
                content=[
                    {"type": "thinking", "thinking": "private reasoning", "signature": "sig"},
                    {"type": "text", "text": "第一段。"},
                    {"type": "text", "text": "第二段。"},
                ],
            ),
        )
    )
    assert model.text("writer", "write") == "第一段。第二段。"


def test_json_compatibility_mode_is_explicit_and_locally_validated():
    captured = []

    def handler(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200, json=response('{"world":"incomplete"}'))

    model = provider(handler, structured=False)
    with pytest.raises(StructuredOutputError):
        model.structured("editor", "plan", Bible)
    assert "output_config" not in captured[0]
    assert "Schema" in captured[0]["messages"][0]["content"]


@pytest.mark.parametrize("stop", ["max_tokens", "refusal", "tool_use", "pause_turn", None])
def test_nonfinal_responses_are_never_accepted(stop):
    model = provider(lambda req: httpx.Response(200, json=response("unfinished", stop)))
    with pytest.raises(ModelError):
        model.text("writer", "write")
    assert len(model.calls) == 1


def test_empty_response_and_provider_errors_do_not_leak_secrets_or_fallback():
    model = provider(lambda req: httpx.Response(200, json=response("", content=[])))
    with pytest.raises(ModelError, match="空正文"):
        model.text("writer", "write")
    captured = []

    def handler(req):
        captured.append(req.url.path)
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "secret body"},
            },
        )

    model = provider(handler)
    with pytest.raises(ModelError) as exc:
        model.text("writer", "write")
    assert "secret body" not in str(exc.value)
    assert captured == ["/v1/messages"]


def test_factory_and_provider_specific_environment(monkeypatch):
    monkeypatch.setenv("SCRIPTOR_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-claude")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anthropic.invalid/")
    monkeypatch.setenv("OPENAI_API_KEY", "other-secret")
    settings = Settings.from_env()
    assert settings.api_key == "anthropic-key"
    assert settings.model == "test-claude"
    assert settings.base_url == "https://anthropic.invalid"
    assert isinstance(create_model(settings), AnthropicModel)
    assert isinstance(create_model(Settings()), ResponsesModel)
    monkeypatch.setenv("SCRIPTOR_PROVIDER", "typo")
    with pytest.raises(ModelError):
        create_model(Settings(provider="typo"))
    from scriptor.errors import ScriptorError

    with pytest.raises(ScriptorError, match="SCRIPTOR_PROVIDER"):
        Settings.from_env()


@pytest.mark.parametrize("schema", [NarrativeBrief, LiteraryReview, SourceReview])
def test_actual_workflow_schemas_are_transformed_and_sent(schema):
    captured = []

    def handler(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200, json=response("{}"))

    model = provider(handler)
    with pytest.raises(StructuredOutputError):
        model.structured("editor", "review", schema)
    assert captured[0]["output_config"]["format"]["schema"]["$defs"]


def test_real_sdk_completes_director_writer_literary_and_fact_pipeline(setup):
    from .conftest import literary_review, narrative_brief, prepare

    svc, fake, book_id = setup
    prepare(svc, fake, book_id)
    paths = []

    def handler(req):
        paths.append(req.url.path)
        body = json.loads(req.content)
        schema = body.get("output_config", {}).get("format", {}).get("schema", {})
        outputs = {
            "NarrativeBrief": narrative_brief().model_dump_json(),
            "LiteraryReview": literary_review().model_dump_json(),
            "SourceReview": json.dumps(
                {
                    "summary": "确认来信",
                    "facts": [],
                    "contradictions": [],
                    "criteria": [{"criterion_id": 1, "achieved": True, "source_ids": [1]}],
                    "confidence": 0.95,
                }
            ),
        }
        return httpx.Response(
            200, json=response(outputs.get(schema.get("title"), "林海确认了姐姐的笔迹。"))
        )

    svc.model = provider(handler)
    chapter = svc.step(book_id)
    assert chapter["content"] == "林海确认了姐姐的笔迹。"
    assert chapter["review"]["criteria"][0]["evidence"] == [chapter["content"]]
    assert chapter["review"]["literary_review"]["verdict"] == "accept"
    assert paths == ["/v1/messages"] * 4
    assert len(svc.repo.runs(book_id)[0]["calls"]) == 4


def test_native_schema_still_enforces_removed_constraints_locally():
    payload = bible().model_dump()
    payload["world"] = " "
    model = provider(lambda req: httpx.Response(200, json=response(json.dumps(payload))))
    with pytest.raises(StructuredOutputError, match="Bible"):
        model.structured("editor", "outline", Bible)


def test_anthropic_health_and_readonly_need_no_credentials(tmp_path):
    from fastapi.testclient import TestClient

    from scriptor.api import create_app

    settings = Settings(provider="anthropic", database=tmp_path / "anthropic.db")
    assert settings.base_url == "https://api.anthropic.com"
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "provider": "anthropic",
            "api_format": "messages",
        }
        assert client.get("/api/books").json() == []
