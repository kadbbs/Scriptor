"""Explicit provider transports with shared local contract validation."""

import json
from typing import Protocol, TypeVar

from anthropic import Anthropic, transform_schema
from anthropic import APIError as AnthropicAPIError
from openai import APIError, OpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings
from .errors import ModelError, StructuredOutputError

T = TypeVar("T", bound=BaseModel)


class Model(Protocol):
    def text(self, instructions: str, prompt: str) -> str: ...

    def structured(self, instructions: str, prompt: str, schema: type[T]) -> T: ...


class _ModelClient:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self._client = client
        self.calls: list[dict] = []

    def close(self):
        if self._client is not None:
            self._client.close()

    def text(self, instructions: str, prompt: str) -> str:
        return self._request(instructions, prompt)

    def structured(self, instructions: str, prompt: str, schema: type[T]) -> T:
        raw = self._request(instructions, prompt, schema)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"模型返回的数据不符合 {schema.__name__}，未写入故事状态"
            ) from exc


class ResponsesModel(_ModelClient):
    @property
    def client(self):
        if self._client is None:
            if not self.settings.api_key or not self.settings.model:
                raise ModelError("请配置 OPENAI_API_KEY 和 OPENAI_MODEL；服务端必须支持 /responses")
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                max_retries=2,
            )
        return self._client

    def _request(self, instructions, prompt, schema=None):
        kwargs = {}
        if schema is not None:
            if self.settings.structured_output:
                kwargs["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": schema.__name__,
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    }
                }
            else:
                prompt += "\n只返回符合以下 Schema 的 JSON 对象：\n" + json.dumps(
                    schema.model_json_schema(), ensure_ascii=False
                )
        try:
            response = self.client.responses.create(
                model=self.settings.model,
                instructions=instructions,
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                store=False,
                max_output_tokens=self.settings.max_output_tokens,
                **kwargs,
            )
        except APIError as exc:
            code = getattr(exc, "status_code", None)
            raise ModelError(
                f"Responses 请求失败（{type(exc).__name__}, HTTP {code or 'network'}）；请检查端点、模型和 Schema 支持"
            ) from exc
        usage = getattr(response, "usage", None)
        self.calls.append(
            {
                "provider": "openai",
                "response_id": response.id,
                "model": response.model,
                "usage": usage.model_dump() if usage else None,
                "status": response.status,
            }
        )
        if response.status != "completed":
            raise ModelError(f"模型输出未完成：{response.status}，请调整输出上限后重试")
        for item in response.output:
            for part in getattr(item, "content", []):
                if getattr(part, "type", "") == "refusal":
                    raise ModelError("模型拒绝了本次生成，请调整写作要求")
        if not response.output_text or not response.output_text.strip():
            raise ModelError("Responses 返回空正文")
        return response.output_text.strip()


class AnthropicModel(_ModelClient):
    @property
    def client(self):
        if self._client is None:
            if not self.settings.api_key or not self.settings.model:
                raise ModelError(
                    "请配置 ANTHROPIC_API_KEY 和 ANTHROPIC_MODEL；服务端必须支持 /v1/messages"
                )
            self._client = Anthropic(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                max_retries=2,
            )
        return self._client

    def _request(self, instructions, prompt, schema=None):
        kwargs = {}
        if schema is not None:
            if self.settings.structured_output:
                kwargs["output_config"] = {
                    "format": {"type": "json_schema", "schema": transform_schema(schema)}
                }
            else:
                prompt += "\n只返回符合以下 Schema 的 JSON 对象：\n" + json.dumps(
                    schema.model_json_schema(), ensure_ascii=False
                )
        try:
            response = self.client.messages.create(
                model=self.settings.model,
                system=instructions,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.settings.max_output_tokens,
                **kwargs,
            )
        except AnthropicAPIError as exc:
            code = getattr(exc, "status_code", None)
            raise ModelError(
                f"Anthropic 请求失败（{type(exc).__name__}, HTTP {code or 'network'}）；请检查端点、模型和结构化输出支持"
            ) from exc
        usage = response.usage.model_dump()
        usage["total_tokens"] = (
            usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
        )
        self.calls.append(
            {
                "provider": "anthropic",
                "response_id": response.id,
                "model": response.model,
                "usage": usage,
                "status": response.stop_reason,
            }
        )
        if response.stop_reason != "end_turn":
            raise ModelError(
                f"Anthropic 输出未正常完成：{response.stop_reason}；未采纳，请检查输出上限或请求"
            )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise ModelError("Anthropic 返回空正文")
        return text


def create_model(settings: Settings) -> Model:
    if settings.provider == "openai":
        return ResponsesModel(settings)
    if settings.provider == "anthropic":
        return AnthropicModel(settings)
    raise ModelError("SCRIPTOR_PROVIDER 仅支持 openai 或 anthropic")
