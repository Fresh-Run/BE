"""Supabase client setup.

Two cached clients with distinct roles:

  - get_supabase()       -> anon (public) key. Used ONLY for auth /
    token validation. Subject to RLS.
  - get_supabase_admin() -> service_role (secret) key. Used for backend
    DATA access. BYPASSES RLS, so it must never leave the server.

Splitting them lets us turn on RLS later (as a backstop against the anon
key) without breaking the backend's own reads/writes.
"""

from functools import lru_cache

import httpx
from postgrest.constants import DEFAULT_POSTGREST_CLIENT_TIMEOUT
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.core.config import settings


def _http1_options() -> SyncClientOptions:
    """HTTP/1.1 강제 httpx 클라이언트를 주입하는 옵션 (호출마다 새 인스턴스).

    서브클라이언트 기본은 http2=True인데, 유휴 keepalive h2 연결의 stale
    재사용이 간헐 502를 냈다(운영 관측 2026-07-08~11, 4회). HTTP/1.1은
    재사용 직전 소켓 체크로 죽은 연결을 폐기하고, 실패해도 다중화가 없어
    1요청만 영향. keepalive_expiry 단축은 기본 5s에서도 재발해 기각.
    anon/admin에 각각 별도 인스턴스 — 헤더 교차 리스크 차단.
    """
    return SyncClientOptions(
        httpx_client=httpx.Client(
            # http2 미지정 = HTTP/1.1. timeout·redirect는 기존 내부 기본과 동일.
            timeout=DEFAULT_POSTGREST_CLIENT_TIMEOUT,
            follow_redirects=True,
        )
    )


@lru_cache
def get_supabase() -> Client:
    """Return the cached anon Supabase client (for auth / token validation).

    Raises:
        RuntimeError: if SUPABASE_URL / SUPABASE_KEY are not configured.
    """
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
            "in your environment (see .env.example)."
        )
    return create_client(
        settings.supabase_url, settings.supabase_key, options=_http1_options()
    )


@lru_cache
def get_supabase_admin() -> Client:
    """Return the cached service_role Supabase client (for backend data access).

    Bypasses RLS — server-side use only. Never expose this key to clients.

    Raises:
        RuntimeError: if SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "Supabase admin client is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in your environment (see .env.example)."
        )
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=_http1_options(),
    )
