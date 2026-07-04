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

from supabase import Client, create_client

from app.core.config import settings


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
    return create_client(settings.supabase_url, settings.supabase_key)


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
        settings.supabase_url, settings.supabase_service_role_key
    )
