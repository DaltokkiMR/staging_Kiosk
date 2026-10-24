"""LLM 클라이언트 (Anthropic Claude).

ANTHROPIC_API_KEY 가 없거나 호출이 실패하면 None 을 돌려주고,
호출한 쪽에서 규칙 기반 대체 로직을 쓰도록 되어 있습니다. (데모가 키 없이도 돌아가게)
"""
import json
import logging
import re

from ..config import settings

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and settings.ANTHROPIC_API_KEY:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def is_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def complete(system: str, messages: list[dict], max_tokens: int = 1024) -> str | None:
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=settings.LLM_MODEL, max_tokens=max_tokens, system=system, messages=messages
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    except Exception as e:  # 네트워크/키 오류 시 대체 로직으로
        log.warning("LLM 호출 실패: %s", e)
        return None


def complete_json(system: str, messages: list[dict], max_tokens: int = 1024) -> dict | None:
    text = complete(system + "\n\n반드시 JSON 객체 하나만 출력하세요. 설명이나 코드블록 없이.", messages, max_tokens)
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
