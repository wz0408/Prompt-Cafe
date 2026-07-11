import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    Fernet = None
    InvalidToken = Exception
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.dependencies import JWT_SECRET_KEY, AuthContext, IS_PRODUCTION, get_auth_context, get_current_user, get_db
from app.db import models
from app.schemas.ai import (
    AIApiKeyStatusResponse,
    AIGuestConfigResponse,
    AIDeleteApiKeyResponse,
    AIGuestQuotaResponse,
    AIModelListResponse,
    AIPolishPromptRequest,
    AIPolishPromptResponse,
    AISaveApiKeyRequest,
    AITestPromptRequest,
    AITestPromptResponse,
    AITestRecordDetailResponse,
    AITestRecordListResponse,
)


router = APIRouter()
CHINA_TIMEZONE = timezone(timedelta(hours=8))
DEFAULT_GUEST_DAILY_LIMIT = 10
DEFAULT_AI_KEY_SECRET = "prompt-cafe-dev-ai-key-secret"
AI_KEY_SECRET = os.getenv("PROMPT_CAFE_AI_KEY_SECRET", DEFAULT_AI_KEY_SECRET)
if IS_PRODUCTION and AI_KEY_SECRET == DEFAULT_AI_KEY_SECRET:
    raise RuntimeError("PROMPT_CAFE_AI_KEY_SECRET must be configured in production")
if AI_KEY_SECRET == DEFAULT_AI_KEY_SECRET:
    warnings.warn(
        "PROMPT_CAFE_AI_KEY_SECRET is not configured; using the development AI key secret.",
        RuntimeWarning,
        stacklevel=2,
    )
PROVIDER_SETTINGS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "protocol": "openai",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "protocol": "openai",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-haiku-latest",
        "models": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
        "protocol": "anthropic",
    },
    "custom": {
        "default_model": "custom-model",
        "models": [],
        "protocol": "openai",
    },
}


class AIProviderError(Exception):
    def __init__(self, code: str, message: str, timeout: bool = False):
        self.code = code
        self.message = message
        self.timeout = timeout
        super().__init__(message)


def now_cn() -> datetime:
    return datetime.now(CHINA_TIMEZONE)


def naive_utc_now() -> datetime:
    return datetime.utcnow()


def success(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 0, "message": "success", "data": data}


def mask_api_key(api_key: str) -> str:
    value = api_key.strip()
    if len(value) <= 8:
        return f"{value[:2]}****{value[-2:]}"
    return f"{value[:4]}****{value[-4:]}"


def _key_stream(secret: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hashlib.sha256(secret + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(output[:length])


def _fernet() -> Any:
    if Fernet is None:
        raise RuntimeError("cryptography is required for AI API Key encryption")
    key = base64.urlsafe_b64encode(hashlib.sha256(AI_KEY_SECRET.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    return "fernet:" + _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key: str) -> str:
    if encrypted_api_key.startswith("fernet:"):
        try:
            return _fernet().decrypt(encrypted_api_key[len("fernet:") :].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Stored API Key cannot be decrypted") from exc

    # Backward compatibility for keys saved before the Fernet migration.
    try:
        payload = base64.urlsafe_b64decode(encrypted_api_key.encode("ascii"))
        if len(payload) <= 16:
            return encrypted_api_key
        nonce, encrypted = payload[:16], payload[16:]
        secret = hashlib.sha256(JWT_SECRET_KEY.encode("utf-8")).digest()
        stream = _key_stream(secret, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream)).decode("utf-8")
    except Exception:
        return encrypted_api_key


def normalized_base_url(provider: str, base_url: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    return str(PROVIDER_SETTINGS[provider]["base_url"]).rstrip("/")


def api_key_status_data(api_key: models.AIApiKey | None, *, saved: bool | None = None) -> dict[str, Any]:
    if not api_key:
        return {
            "configured": False,
            "saved": saved,
            "maskedKey": None,
            "provider": None,
            "baseUrl": None,
            "defaultModel": None,
            "verified": False,
            "updatedAt": None,
        }
    return {
        "configured": api_key.status == "active",
        "saved": saved,
        "maskedKey": api_key.key_mask,
        "provider": api_key.provider,
        "baseUrl": api_key.base_url,
        "defaultModel": api_key.default_model,
        "verified": bool(api_key.is_verified),
        "updatedAt": api_key.updated_at,
    }


def get_request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def get_guest_session_id(request: Request) -> str:
    session_id = request.headers.get("x-guest-session-id") or request.cookies.get("guestSessionId")
    return (session_id or f"guest:{get_request_ip(request) or 'anonymous'}")[:100]


def get_optional_user(auth_context: AuthContext, db: Session) -> models.User | None:
    if auth_context.is_guest or not auth_context.token_valid or not auth_context.user_id:
        return None
    try:
        user_id = UUID(auth_context.user_id)
    except ValueError:
        return None
    user = db.query(models.User).filter(models.User.id == user_id).first()
    return user if user and user.status == "active" else None


def get_active_system_config(db: Session) -> models.SystemAIConfig | None:
    return (
        db.query(models.SystemAIConfig)
        .filter(models.SystemAIConfig.is_enabled.is_(True))
        .order_by(desc(models.SystemAIConfig.is_default), desc(models.SystemAIConfig.updated_at))
        .first()
    )


def get_guest_daily_limit(db: Session) -> int:
    system_config = get_active_system_config(db)
    return (system_config.daily_guest_limit or DEFAULT_GUEST_DAILY_LIMIT) if system_config else DEFAULT_GUEST_DAILY_LIMIT


def get_guest_quota_row(db: Session, guest_session_id: str, day) -> models.GuestAIQuota | None:
    return (
        db.query(models.GuestAIQuota)
        .filter(
            models.GuestAIQuota.guest_session_id == guest_session_id,
            models.GuestAIQuota.usage_date == day,
        )
        .first()
    )


def quota_data(db: Session, guest_session_id: str) -> dict[str, Any]:
    current = now_cn()
    day = current.date()
    limit = get_guest_daily_limit(db)
    quota = get_guest_quota_row(db, guest_session_id, day)
    used = quota.total_count or 0 if quota else 0
    reset_at = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=CHINA_TIMEZONE)
    remaining = max(limit - used, 0)
    return {
        "dailyLimit": limit,
        "usedCount": used,
        "remainingCount": remaining,
        "resetAt": reset_at,
        "allowed": remaining > 0,
    }


def reserve_guest_quota(db: Session, request: Request, guest_session_id: str, call_type: str) -> None:
    current = now_cn()
    day = current.date()
    limit = get_guest_daily_limit(db)
    quota = get_guest_quota_row(db, guest_session_id, day)
    now = naive_utc_now()
    if quota is None:
        quota = models.GuestAIQuota(
            guest_session_id=guest_session_id,
            ip_address=get_request_ip(request),
            usage_date=day,
            polish_count=0,
            test_count=0,
            total_count=0,
            daily_limit=limit,
            created_at=now,
            updated_at=now,
        )
        db.add(quota)
        db.flush()
    if (quota.total_count or 0) >= (quota.daily_limit or limit):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Guest AI quota exceeded")
    if call_type == "polish":
        quota.polish_count = (quota.polish_count or 0) + 1
    else:
        quota.test_count = (quota.test_count or 0) + 1
    quota.total_count = (quota.total_count or 0) + 1
    quota.last_called_at = now
    quota.updated_at = now


def get_owned_or_public_prompt(db: Session, prompt_id: UUID, user: models.User | None) -> models.Prompt:
    prompt = db.query(models.Prompt).filter(models.Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt not found")
    if prompt.visibility != "public" and (not user or prompt.user_id != user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No permission to access this Prompt")
    return prompt


def resolve_config(db: Session, user: models.User | None, requested_provider: str | None = None) -> dict[str, str]:
    if user:
        config = (
            db.query(models.AIApiKey)
            .filter(models.AIApiKey.user_id == user.id, models.AIApiKey.status == "active")
            .first()
        )
        if config is None or not config.is_verified:
            raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "Please configure a verified API Key first")
        source = "user"
    else:
        config = get_active_system_config(db)
        if config is None:
            raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "Guest AI service is not configured")
        source = "system_default"
    if requested_provider and requested_provider != config.provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selected provider does not match configured API Key")
    return {
        "source": source,
        "provider": config.provider,
        "base_url": config.base_url,
        "api_key": decrypt_api_key(config.encrypted_api_key),
        "model": config.default_model,
    }


def render_template(template: str, variables: dict[str, str]) -> str:
    def replace(match):
        name = match.group(1).strip()
        return variables.get(name, match.group(0))

    return re.sub(r"\{\{\s*([^{}\s]+)\s*\}\}", replace, template)


def external_headers(config: dict[str, str]) -> dict[str, str]:
    if PROVIDER_SETTINGS.get(config["provider"], {}).get("protocol") == "anthropic":
        return {
            "x-api-key": config["api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    return {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}


def models_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return f"{base_url}/models"


def chat_url(config: dict[str, str]) -> str:
    base_url = config["base_url"].rstrip("/")
    if PROVIDER_SETTINGS.get(config["provider"], {}).get("protocol") == "anthropic":
        return f"{base_url}/messages"
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def request_external(request: urllib.request.Request, timeout: int = 60) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise AIProviderError("invalid_response", "AI provider returned an invalid response")
            return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIProviderError(str(exc.code), detail or str(exc.reason)) from exc
    except urllib.error.URLError as exc:
        raise AIProviderError("network_error", str(exc.reason)) from exc
    except TimeoutError as exc:
        raise AIProviderError("timeout", "AI request timed out", timeout=True) from exc
    except (ValueError, TypeError) as exc:
        raise AIProviderError("invalid_response", "AI provider returned invalid JSON") from exc


def verify_api_key(provider: str, base_url: str, api_key: str) -> None:
    config = {"provider": provider, "base_url": base_url, "api_key": api_key}
    request = urllib.request.Request(models_url(base_url), headers=external_headers(config), method="GET")
    request_external(request, timeout=20)


def call_model(
    config: dict[str, str],
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> tuple[str, dict[str, int], int]:
    protocol = PROVIDER_SETTINGS.get(config["provider"], {}).get("protocol", "openai")
    if protocol == "anthropic":
        system_text = "\n".join(item["content"] for item in messages if item["role"] == "system")
        user_messages = [item for item in messages if item["role"] != "system"]
        body: dict[str, Any] = {
            "model": model,
            "messages": user_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            body["system"] = system_text
    else:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    request = urllib.request.Request(
        chat_url(config),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=external_headers(config),
        method="POST",
    )
    started = time.perf_counter()
    payload = request_external(request)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if protocol == "anthropic":
        content = payload.get("content") or []
        output = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        raw_usage = payload.get("usage") or {}
        prompt_tokens = raw_usage.get("input_tokens", 0) or 0
        completion_tokens = raw_usage.get("output_tokens", 0) or 0
    else:
        choices = payload.get("choices") or []
        if not choices:
            raise AIProviderError("invalid_response", "AI provider returned no completion")
        output = (choices[0].get("message") or {}).get("content") or choices[0].get("text") or ""
        raw_usage = payload.get("usage") or {}
        prompt_tokens = raw_usage.get("prompt_tokens", 0) or 0
        completion_tokens = raw_usage.get("completion_tokens", 0) or 0
    return output, {
        "promptTokens": int(prompt_tokens),
        "completionTokens": int(completion_tokens),
        "totalTokens": int(raw_usage.get("total_tokens", prompt_tokens + completion_tokens) or 0),
    }, latency_ms


def add_audit_log(db: Session, user: models.User, action: str, detail: dict[str, Any]) -> None:
    db.add(
        models.AuditLog(
            actor_id=user.id,
            actor_role=user.role,
            action=action,
            target_type="ai_api_key",
            target_id=user.id,
            detail=detail,
        )
    )


def create_call_record(
    db: Session,
    request: Request,
    *,
    user: models.User | None,
    guest_session_id: str | None,
    prompt_id: UUID | None,
    call_type: str,
    config: dict[str, str],
    model: str,
    input_summary: str,
    rendered_prompt: str,
    output_text: str | None,
    suggestions: list[str] | None,
    variables: dict[str, str] | None,
    temperature: float,
    max_tokens: int,
    usage: dict[str, int] | None,
    latency_ms: int | None,
    record_status: str = "success",
    error: AIProviderError | None = None,
) -> models.AICallRecord:
    record = models.AICallRecord(
        user_id=user.id if user else None,
        guest_session_id=guest_session_id,
        prompt_id=prompt_id,
        call_type=call_type,
        api_key_source=config["source"],
        provider=config["provider"],
        model=model,
        input_summary=input_summary,
        rendered_user_prompt=rendered_prompt,
        output_text=output_text,
        suggestions=suggestions,
        variables=variables,
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_tokens=usage["promptTokens"] if usage else None,
        completion_tokens=usage["completionTokens"] if usage else None,
        total_tokens=usage["totalTokens"] if usage else None,
        latency_ms=latency_ms,
        status=record_status,
        error_code=error.code if error else None,
        error_message=error.message if error else None,
        ip_address=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        created_at=naive_utc_now(),
    )
    db.add(record)
    db.flush()
    return record


def summarize(text: str | None, limit: int = 100) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact if len(compact) <= limit else f"{compact[:limit]}..."


def parse_polish_output(text: str) -> tuple[str, list[str]]:
    candidates = [text.strip()]
    candidates.extend(
        match.strip()
        for match in re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    )
    for candidate in candidates:
        try:
            result = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(result, dict):
            continue
        optimized = result.get("optimized") or result.get("optimizedPrompt")
        suggestions = result.get("suggestions")
        if not isinstance(optimized, str) or not optimized.strip():
            continue
        suggestion_items = suggestions if isinstance(suggestions, list) else []
        return optimized, [str(item) for item in suggestion_items if str(item).strip()]
    return text, []


def external_failure(exc: AIProviderError) -> HTTPException:
    http_status = status.HTTP_504_GATEWAY_TIMEOUT if exc.timeout else status.HTTP_502_BAD_GATEWAY
    return HTTPException(http_status, f"AI service request failed: {exc.message}")


@router.get("/guest/quota", response_model=AIGuestQuotaResponse, summary="Query guest AI quota")
def get_guest_quota(request: Request, db: Session = Depends(get_db)):
    return success(quota_data(db, get_guest_session_id(request)))


@router.get("/guest/config", response_model=AIGuestConfigResponse, summary="Query guest AI default config")
def get_guest_config(request: Request, db: Session = Depends(get_db)):
    config = get_active_system_config(db)
    quota = quota_data(db, get_guest_session_id(request))
    return success({
        "configured": bool(config),
        "provider": config.provider if config else None,
        "defaultModel": config.default_model if config else None,
        "dailyLimit": quota["dailyLimit"],
        "remainingCount": quota["remainingCount"],
        "allowed": bool(config) and quota["allowed"],
    })


@router.put("/api-key", response_model=AIApiKeyStatusResponse, summary="Save current user's AI API key")
def save_api_key(
    payload: AISaveApiKeyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    api_key = payload.apiKey.strip()
    base_url = normalized_base_url(payload.provider, str(payload.baseUrl) if payload.baseUrl else None)
    try:
        verify_api_key(payload.provider, base_url, api_key)
    except AIProviderError as exc:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code in {"400", "401", "403"}
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code, f"API Key verification failed: {exc.message}") from exc
    stored = db.query(models.AIApiKey).filter(models.AIApiKey.user_id == current_user.id).first()
    now = naive_utc_now()
    if stored is None:
        stored = models.AIApiKey(user_id=current_user.id, created_at=now)
        db.add(stored)
    stored.provider = payload.provider
    stored.base_url = base_url
    stored.encrypted_api_key = encrypt_api_key(api_key)
    stored.key_mask = mask_api_key(api_key)
    stored.default_model = payload.defaultModel or str(PROVIDER_SETTINGS[payload.provider]["default_model"])
    stored.is_verified = True
    stored.last_verified_at = now
    stored.status = "active"
    stored.updated_at = now
    add_audit_log(
        db,
        current_user,
        "save_ai_api_key",
        {"provider": payload.provider, "baseUrl": base_url, "defaultModel": stored.default_model},
    )
    db.commit()
    db.refresh(stored)
    return success(api_key_status_data(stored, saved=True))


@router.delete("/api-key", response_model=AIDeleteApiKeyResponse, summary="Delete current user's AI API key")
def delete_api_key(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stored = db.query(models.AIApiKey).filter(models.AIApiKey.user_id == current_user.id).first()
    if stored:
        provider = stored.provider
        db.delete(stored)
    else:
        provider = None
    deleted_at = naive_utc_now()
    add_audit_log(db, current_user, "delete_ai_api_key", {"provider": provider})
    db.commit()
    return success({"deleted": True, "deletedAt": deleted_at})


@router.get("/api-key/status", response_model=AIApiKeyStatusResponse, summary="Query API key status")
def get_api_key_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stored = db.query(models.AIApiKey).filter(models.AIApiKey.user_id == current_user.id).first()
    return success(api_key_status_data(stored))


@router.get("/models", response_model=AIModelListResponse, summary="Query supported AI models")
def get_models():
    items = [
        {"provider": provider, "models": settings["models"]}
        for provider, settings in PROVIDER_SETTINGS.items()
    ]
    return success({"items": items})


@router.post("/polish", response_model=AIPolishPromptResponse, summary="Polish Prompt with AI")
def polish_prompt(
    payload: AIPolishPromptRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    user = get_optional_user(auth_context, db)
    prompt = get_owned_or_public_prompt(db, payload.promptId, user) if payload.promptId else None
    original = payload.content.strip() if payload.content and payload.content.strip() else prompt.user_prompt
    config = resolve_config(db, user, payload.provider)
    if not user and payload.model and payload.model != config["model"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Guests must use the system default model")
    model = payload.model or config["model"]
    guest_session_id = None if user else get_guest_session_id(request)
    if guest_session_id:
        reserve_guest_quota(db, request, guest_session_id, "polish")
    preferences = {
        "tone": payload.tone or "formal",
        "language": payload.language or "zh-CN",
        "length": payload.lengthPreference or "medium",
    }
    instructions = (
        "Polish the provided prompt while retaining its intent and variables. "
        "Return a JSON object only with fields optimized (string) and suggestions (array of strings); "
        "do not wrap it in Markdown code fences or add explanatory prose. "
        f"Tone: {preferences['tone']}; language: {preferences['language']}; length: {preferences['length']}.\n"
        f"Prompt:\n{original}"
    )
    try:
        output, usage, latency_ms = call_model(
            config,
            [{"role": "user", "content": instructions}],
            model,
            temperature=0.3,
            max_tokens=2048,
        )
        optimized, suggestions = parse_polish_output(output)
        create_call_record(
            db,
            request,
            user=user,
            guest_session_id=guest_session_id,
            prompt_id=prompt.id if prompt else None,
            call_type="polish",
            config=config,
            model=model,
            input_summary=summarize(original),
            rendered_prompt=original,
            output_text=optimized,
            suggestions=suggestions,
            variables=None,
            temperature=0.3,
            max_tokens=2048,
            usage=usage,
            latency_ms=latency_ms,
        )
        db.commit()
        return success({
            "original": original,
            "optimized": optimized,
            "suggestions": suggestions,
            "provider": config["provider"],
            "model": model,
            "latencyMs": latency_ms,
        })
    except AIProviderError as exc:
        create_call_record(
            db,
            request,
            user=user,
            guest_session_id=guest_session_id,
            prompt_id=prompt.id if prompt else None,
            call_type="polish",
            config=config,
            model=model,
            input_summary=summarize(original),
            rendered_prompt=original,
            output_text=None,
            suggestions=None,
            variables=None,
            temperature=0.3,
            max_tokens=2048,
            usage=None,
            latency_ms=None,
            record_status="failed",
            error=exc,
        )
        db.commit()
        raise external_failure(exc) from exc


@router.post("/test", response_model=AITestPromptResponse, summary="Test Prompt with AI")
def test_prompt(
    payload: AITestPromptRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    user = get_optional_user(auth_context, db)
    prompt = get_owned_or_public_prompt(db, payload.promptId, user) if payload.promptId else None
    config = resolve_config(db, user, payload.provider)
    guest_session_id = None if user else get_guest_session_id(request)
    if guest_session_id:
        reserve_guest_quota(db, request, guest_session_id, "test")
    rendered_prompt = render_template(payload.content, payload.variables)
    try:
        output, usage, latency_ms = call_model(
            config,
            [{"role": "user", "content": rendered_prompt}],
            payload.model,
            payload.temperature,
            payload.maxTokens,
        )
        record = create_call_record(
            db,
            request,
            user=user,
            guest_session_id=guest_session_id,
            prompt_id=prompt.id if prompt else None,
            call_type="test",
            config=config,
            model=payload.model,
            input_summary=summarize(rendered_prompt),
            rendered_prompt=rendered_prompt,
            output_text=output,
            suggestions=None,
            variables=payload.variables,
            temperature=payload.temperature,
            max_tokens=payload.maxTokens,
            usage=usage,
            latency_ms=latency_ms,
        )
        db.commit()
        db.refresh(record)
        return success({
            "recordId": record.id,
            "promptId": record.prompt_id,
            "provider": config["provider"],
            "model": payload.model,
            "renderedPrompt": rendered_prompt,
            "output": output,
            "latencyMs": latency_ms,
            "tokenUsage": usage,
            "createdAt": record.created_at,
        })
    except AIProviderError as exc:
        create_call_record(
            db,
            request,
            user=user,
            guest_session_id=guest_session_id,
            prompt_id=prompt.id if prompt else None,
            call_type="test",
            config=config,
            model=payload.model,
            input_summary=summarize(rendered_prompt),
            rendered_prompt=rendered_prompt,
            output_text=None,
            suggestions=None,
            variables=payload.variables,
            temperature=payload.temperature,
            max_tokens=payload.maxTokens,
            usage=None,
            latency_ms=None,
            record_status="failed",
            error=exc,
        )
        db.commit()
        raise external_failure(exc) from exc


@router.get("/test-records", response_model=AITestRecordListResponse, summary="Query AI test records")
def get_test_records(
    promptId: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.AICallRecord).filter(
        models.AICallRecord.user_id == current_user.id,
        models.AICallRecord.call_type == "test",
    )
    if promptId:
        query = query.filter(models.AICallRecord.prompt_id == promptId)
    total = query.count()
    records = query.order_by(desc(models.AICallRecord.created_at)).offset((page - 1) * pageSize).limit(pageSize).all()
    items = [{
        "id": record.id,
        "promptId": record.prompt_id,
        "provider": record.provider,
        "model": record.model,
        "inputSummary": summarize(record.input_summary),
        "outputSummary": summarize(record.output_text),
        "latencyMs": record.latency_ms or 0,
        "createdAt": record.created_at,
    } for record in records]
    return success({"items": items, "pagination": {"page": page, "pageSize": pageSize, "total": total}})


@router.get("/test-records/{recordId}", response_model=AITestRecordDetailResponse, summary="Get AI test record detail")
def get_test_record_detail(
    recordId: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    record = db.query(models.AICallRecord).filter(
        models.AICallRecord.id == recordId,
        models.AICallRecord.user_id == current_user.id,
        models.AICallRecord.call_type == "test",
    ).first()
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI test record not found")
    return success({
        "id": record.id,
        "promptId": record.prompt_id,
        "provider": record.provider,
        "model": record.model,
        "inputVariables": record.variables,
        "renderedPrompt": record.rendered_user_prompt or "",
        "output": record.output_text or "",
        "latencyMs": record.latency_ms or 0,
        "tokenUsage": {
            "promptTokens": record.prompt_tokens or 0,
            "completionTokens": record.completion_tokens or 0,
            "totalTokens": record.total_tokens or 0,
        },
        "createdAt": record.created_at,
    })
