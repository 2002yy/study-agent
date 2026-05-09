import os
from dotenv import load_dotenv

load_dotenv()

_config_cache: dict | None = None


def _load() -> dict:
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "base_url": os.getenv("OPENAI_BASE_URL", "").strip(),
        "flash_model": os.getenv("MODEL_FLASH_NAME", "").strip(),
        "pro_model": os.getenv("MODEL_PRO_NAME", "").strip(),
        "default_profile": os.getenv("DEFAULT_MODEL_PROFILE", "flash").strip(),
    }


def get_config() -> dict:
    global _config_cache
    if _config_cache is None:
        _config_cache = _load()
    return _config_cache


def validate() -> list[str]:
    cfg = get_config()
    errors = []
    if not cfg["api_key"]:
        errors.append("OPENAI_API_KEY 未设置")
    if not cfg["base_url"]:
        errors.append("OPENAI_BASE_URL 未设置")
    if not cfg["flash_model"]:
        errors.append("MODEL_FLASH_NAME 未设置")
    if not cfg["pro_model"]:
        errors.append("MODEL_PRO_NAME 未设置")
    return errors


def reload_config() -> dict:
    global _config_cache
    load_dotenv(override=True)
    _config_cache = _load()

    try:
        from src.llm_client import reset_client

        reset_client()
    except Exception:
        pass

    return _config_cache
