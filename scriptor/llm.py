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

    @staticmethod
    def _json_contract(schema):
        return (
            "\n【结构化输出协议】\n"
            "只返回一个符合以下 JSON Schema 的 JSON 对象。必须使用 Schema 中的英文字段名，"
            "中文创作内容写在字段值中。包含全部 required 字段，遵守类型、枚举、长度与数值约束。"
            "不要输出 Markdown 大纲、代码围栏、解释或 Schema 本身。\nJSON Schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
        )

    def _request_info(self, instructions, prompt, schema, mode=None):
        mode = mode or (
            "text"
            if schema is None
            else "json_schema"
            if self.settings.structured_output
            else "json"
        )
        return {
            "structured_mode": mode,
            "max_output_tokens": self.settings.max_output_tokens,
            "input_chars": len(prompt),
            "system_chars": len(instructions),
            "schema": schema.__name__ if schema is not None else None,
            "native_schema": mode == "json_schema",
        }

    def _api_failure(self, provider, exc, request_info=None):
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
                "request": request_info,
            }
        )
        name = "Anthropic" if provider == "anthropic" else "Responses"
        status = f"HTTP {code}" if code is not None else "network"
        suffix = f"；请求编号 {request_id}" if request_id else ""
        model_name = re.sub(r"[\r\n\t]", " ", self.settings.model)
        if self.settings.api_key:
            model_name = model_name.replace(self.settings.api_key, "[REDACTED]")
        suffix += f"；模型 {model_name[:120]}"
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
        # Some compatible endpoints wrap otherwise complete JSON in a code fence.
        # Never extract a fragment from prose or repair missing/invalid fields.
        fenced = re.fullmatch(
            r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", raw.strip(), re.IGNORECASE
        )
        payload = fenced.group(1) if fenced else raw
        if fenced and self.calls:
            self.calls[-1]["json_envelope_removed"] = True
        try:
            return schema.model_validate_json(payload)
        except ValidationError as exc:
            issues = [
                {"path": ".".join(map(str, e["loc"])) or "$", "type": e["type"]}
                for e in exc.errors(include_input=False, include_context=False, include_url=False)[
                    :10
                ]
            ]
            if self.calls:
                self.calls[-1]["validation"] = {
                    "schema": schema.__name__,
                    "response_chars": len(raw),
                    "output_shape": "json_fence"
                    if fenced
                    else "json_object"
                    if raw.lstrip().startswith("{")
                    else "other",
                    "errors": issues,
                }
            detail = "; ".join(f"{i['path']}: {i['type']}" for i in issues[:3])
            raise StructuredOutputError(
                f"模型返回的数据不符合 {schema.__name__}（{detail}），未写入故事状态",
                raw_output=raw,
                schema_name=schema.__name__,
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
                prompt += self._json_contract(schema)
        request_info = self._request_info(instructions, prompt, schema)
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
            raise self._api_failure("openai", exc, request_info) from exc
        usage = getattr(response, "usage", None)
        self.calls.append(
            {
                "provider": "openai",
                "request": request_info,
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
        mode = (
            "text"
            if schema is None
            else self.settings.anthropic_structured_mode
            if self.settings.structured_output
            else "json"
        )
        if mode not in ("text", "tool", "json_schema", "json"):
            raise ModelError("ANTHROPIC_STRUCTURED_MODE 仅支持 tool、json_schema 或 json")
        if schema is not None:
            if mode == "tool":
                kwargs["tools"] = [
                    {
                        "name": "submit_result",
                        "description": "Submit the complete structured result. Fill all required fields of the supplied schema.",
                        "input_schema": schema.model_json_schema(),
                    }
                ]
                kwargs["tool_choice"] = {"type": "tool", "name": "submit_result"}
                prompt += "\n【提交协议】必须调用 submit_result，将完整结果填入其参数。不要在普通文本中输出方案。本工具只提交数据，不执行外部操作。"
            else:
                if mode == "json_schema":
                    kwargs["output_config"] = {
                        "format": {"type": "json_schema", "schema": transform_schema(schema)}
                    }
                prompt += self._json_contract(schema)
        request_info = self._request_info(instructions, prompt, schema, mode)
        try:
            response = self.client.messages.create(
                model=self.settings.model,
                system=instructions,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.settings.max_output_tokens,
                **kwargs,
            )
        except AnthropicAPIError as exc:
            raise self._api_failure("anthropic", exc, request_info) from exc
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
                "request": request_info,
                "response_id": response.id,
                "model": response.model,
                "usage": usage,
                "status": response.stop_reason,
            }
        )
        if mode == "tool":
            text = "".join(block.text for block in response.content if block.type == "text")
            blocks = [block for block in response.content if block.type == "tool_use"]
            if response.stop_reason not in ("tool_use", "end_turn"):
                raise ModelError(f"Anthropic 工具参数未完整返回：{response.stop_reason}；未采纳")
            if (
                response.stop_reason != "tool_use"
                or len(blocks) != 1
                or blocks[0].name != "submit_result"
                or not isinstance(blocks[0].input, dict)
            ):
                self.calls[-1]["validation"] = {
                    "schema": schema.__name__,
                    "output_shape": "unexpected_tool_response",
                    "errors": [{"path": "$", "type": "missing_or_ambiguous_submit_result"}],
                }
                raise StructuredOutputError(
                    "Anthropic 未返回唯一的 submit_result 工具参数；请确认端点支持 tool_choice，或显式选择 json_schema/json 模式",
                    raw_output=text,
                    schema_name=schema.__name__,
                )
            return json.dumps(blocks[0].input, ensure_ascii=False)
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
