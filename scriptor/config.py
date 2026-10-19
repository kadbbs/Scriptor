import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ScriptorError


@dataclass(frozen=True)
class Settings:
    database: Path = Path("data/scriptor.db")
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 180
    max_output_tokens: int = 12000
    structured_output: bool = True
    context_chars: int = 28000
    provider: str = "openai"
    auto_retries: int = 2
    retry_delay: float = 5

    def __post_init__(self):
        if not self.base_url:
            default = (
                "https://api.anthropic.com"
                if self.provider == "anthropic"
                else "https://api.openai.com/v1"
            )
            object.__setattr__(self, "base_url", default)

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        provider = os.getenv("SCRIPTOR_PROVIDER", "openai").strip().lower()
        if provider not in ("openai", "anthropic"):
            raise ScriptorError("SCRIPTOR_PROVIDER 仅支持 openai 或 anthropic")
        prefix = "ANTHROPIC" if provider == "anthropic" else "OPENAI"
        default_url = (
            "https://api.anthropic.com" if provider == "anthropic" else "https://api.openai.com/v1"
        )
        try:
            result = cls(
                provider=provider,
                auto_retries=int(os.getenv("SCRIPTOR_AUTO_RETRIES", "2")),
                retry_delay=float(os.getenv("SCRIPTOR_RETRY_DELAY", "5")),
                database=Path(os.getenv("SCRIPTOR_DB", "data/scriptor.db")),
                api_key=os.getenv(f"{prefix}_API_KEY", ""),
                base_url=os.getenv(f"{prefix}_BASE_URL", default_url).rstrip("/"),
                model=os.getenv(f"{prefix}_MODEL", ""),
                timeout=float(os.getenv("SCRIPTOR_TIMEOUT", "180")),
                max_output_tokens=int(os.getenv("SCRIPTOR_MAX_OUTPUT_TOKENS", "12000")),
                structured_output=os.getenv("SCRIPTOR_STRUCTURED_OUTPUT", "true").lower() == "true",
                context_chars=int(os.getenv("SCRIPTOR_CONTEXT_CHARS", "28000")),
            )
        except ValueError as exc:
            raise ScriptorError("配置中的数字格式无效") from exc
        if result.timeout <= 0 or result.max_output_tokens < 256 or result.context_chars < 6000:
            raise ScriptorError("timeout 必须 > 0，输出上限 >= 256，上下文字符预算 >= 6000")
        if not 0 <= result.auto_retries <= 5 or not 0 <= result.retry_delay <= 60:
            raise ScriptorError(
                "SCRIPTOR_AUTO_RETRIES 必须为 0–5，SCRIPTOR_RETRY_DELAY 必须为 0–60 秒"
            )
        return result
