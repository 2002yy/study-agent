import os
from dotenv import load_dotenv

load_dotenv()

_config_cache: dict | None = None


def _load() -> dict:
    return {
        "provider_profile": os.getenv("LLM_PROVIDER_PROFILE", "openai").strip().lower(),
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
    try:
        from src.llm_client import get_provider_settings

        get_provider_settings(get_config().get("provider_profile"))
        return []
    except Exception as e:
        return [str(e)]


def reload_config() -> dict:
    global _config_cache
    load_dotenv(override=True)
    _config_cache = _load()

    try:
        from src.llm_client import reset_client

        reset_client()
    except Exception as e:
        from src.log_utils import get_logger
        get_logger().warning("config reload: reset_client failed: %s", e)

    return _config_cache
