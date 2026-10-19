import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ScriptorError


@dataclass(frozen=True)
class Settings:
    database: Path = Path("data/scriptor.db")
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    timeout: float = 180
    max_output_tokens: int = 12000
    structured_output: bool = True
    context_chars: int = 28000

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        try:
            result = cls(
                database=Path(os.getenv("SCRIPTOR_DB", "data/scriptor.db")),
                api_key=os.getenv("OPENAI_API_KEY", ""),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
                model=os.getenv("OPENAI_MODEL", ""),
                timeout=float(os.getenv("SCRIPTOR_TIMEOUT", "180")),
                max_output_tokens=int(os.getenv("SCRIPTOR_MAX_OUTPUT_TOKENS", "12000")),
                structured_output=os.getenv("SCRIPTOR_STRUCTURED_OUTPUT", "true").lower() == "true",
                context_chars=int(os.getenv("SCRIPTOR_CONTEXT_CHARS", "28000")),
            )
        except ValueError as exc:
            raise ScriptorError("配置中的数字格式无效") from exc
        if result.timeout <= 0 or result.max_output_tokens < 256 or result.context_chars < 6000:
            raise ScriptorError("timeout 必须 > 0，输出上限 >= 256，上下文字符预算 >= 6000")
        return result
