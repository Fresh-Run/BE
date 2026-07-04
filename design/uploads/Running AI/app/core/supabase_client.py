"""Supabase client setup.

Exposes a lazily-initialized, cached Supabase client so the rest of the
app can `from app.core.supabase_client import get_supabase` and use it.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_supabase() -> Client:
    """Return a cached Supabase client.

    Raises:
        RuntimeError: if SUPABASE_URL / SUPABASE_KEY are not configured.
    """
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
            "in your environment (see .env.example)."
        )
    return create_client(settings.supabase_url, settings.supabase_key)
