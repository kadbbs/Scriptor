"""Explicit provider transports with shared local contract validation."""

import json
import math
import re
from typing import Protocol, TypeVar

from anthropic import Anthropic, transform_schema
from anthropic import APIConnectionError as AnthropicConnectionError
from anthropic import APIError as AnthropicAPIError
from openai import APIConnectionError, APIError, OpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings
from .errors import ModelError, StructuredOutputError, TransientModelError

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

    def _api_failure(self, provider, exc):
        code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        headers = response.headers if response is not None else {}
        request_id = (
            getattr(exc, "request_id", None)
            or headers.get("request-id")
            or headers.get("x-request-id")
        )
        if request_id:
            request_id = str(request_id)
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", request_id) or (
                self.settings.api_key and self.settings.api_key in request_id
            ):
                request_id = None
        retry_after = None
        try:
            value = (
                float(headers["retry-after"])
                if "retry-after" in headers
                else float(headers["retry-after-ms"]) / 1000
            )
            if math.isfinite(value) and value >= 0:
                retry_after = min(value, 60)
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
        self.calls.append(
            {
                "provider": provider,
                "model": self.settings.model,
                "status": "failed",
                "http_status": code,
                "request_id": request_id,
                "usage": None,
                "error_type": type(exc).__name__,
            }
        )
        name = "Anthropic" if provider == "anthropic" else "Responses"
        status = f"HTTP {code}" if code is not None else "network"
        suffix = f"；请求编号 {request_id}" if request_id else ""
        if code == 429:
            message = f"{name} 请求被限流（{status}）；请稍后重试或检查服务配额"
        elif code is not None and code >= 500:
            message = f"{name} 上游服务暂不可用（{status}）；请稍后重试或检查中转服务的生成线路状态"
        elif isinstance(exc, (APIConnectionError, AnthropicConnectionError)):
            message = f"{name} 连接失败或超时（{status}）；请检查网络或稍后重试"
        elif code == 401:
            message = f"{name} 认证失败（{status}）；请检查所选提供商的 API 密钥"
        elif code == 403:
            message = f"{name} 请求被拒绝（{status}）；请检查账号与模型权限"
        elif code == 404:
            message = f"{name} 端点或模型不存在（{status}）；请核对 BASE_URL 和模型 ID"
        elif code in (400, 422):
            message = f"{name} 请求参数被拒绝（{status}）；请检查模型、输出上限及结构化输出支持"
        else:
            message = f"{name} 请求失败（{type(exc).__name__}, {status}）"
        temporary = (
            code == 429
            or (code is not None and code >= 500)
            or isinstance(exc, (APIConnectionError, AnthropicConnectionError))
        )
        if temporary:
            return TransientModelError(message + suffix, retry_after=retry_after)
        return ModelError(message + suffix)

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
            raise self._api_failure("openai", exc) from exc
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
            raise self._api_failure("anthropic", exc) from exc
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
