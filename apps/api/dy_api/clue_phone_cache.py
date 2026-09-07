"""Bounded, source-bound decryption cache; never caches access decisions."""

from collections import OrderedDict
from threading import RLock
from time import monotonic
from weakref import WeakKeyDictionary

_LOCK = RLock()
_ENGINES = WeakKeyDictionary()
MAX_ENTRIES = 1024
SUCCESS_TTL_SECONDS = 300
FAILURE_TTL_SECONDS = 30


def get_phone(engine, fingerprint: str) -> str | None:
    with _LOCK:
        cache = _ENGINES.get(engine)
        if cache is None or fingerprint not in cache:
            return None
        deadline, phone = cache[fingerprint]
        if deadline <= monotonic():
            del cache[fingerprint]
            return None
        cache.move_to_end(fingerprint)
        return phone


def put_phone(engine, fingerprint: str, phone: str) -> None:
    with _LOCK:
        cache = _ENGINES.setdefault(engine, OrderedDict())
        ttl = SUCCESS_TTL_SECONDS if phone else FAILURE_TTL_SECONDS
        cache[fingerprint] = (monotonic() + ttl, phone)
        cache.move_to_end(fingerprint)
        while len(cache) > MAX_ENTRIES:
            cache.popitem(last=False)
