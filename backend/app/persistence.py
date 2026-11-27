"""
Room state persistence: every party saved to one JSON file.

- Atomic: the snapshot is written to a temp file in the same directory, fsynced,
  then moved over the old file with os.replace, so a crash mid-write leaves the
  previous file intact.
- One writer at a time: a write lock is held across snapshot + write, so an
  older snapshot can never overwrite a newer one.
- Idle expiry: parties with no activity for idle_ttl_seconds are dropped on
  load and on every save.
- Spotify tokens are not written: after a restart the host reconnects Spotify.

Single instance only: two processes would each hold their own PARTIES and
overwrite each other's file. See README, Reliability.
"""
from __future__ import annotations

import contextlib
import functools
import inspect
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from pydantic import ValidationError

from app.models.schemas import PartySession

# Guards PARTIES and everything inside it. Endpoints hold it while they change
# state; save() holds it while it takes the snapshot. Never call save() while
# holding it (save takes the write lock first, then this one).
STATE_LOCK = threading.RLock()

NOT_SAVED = {"spotify_token", "spotify_refresh"}
FORMAT_VERSION = 1


class RoomStore:
    def __init__(self, path: str | os.PathLike | None, idle_ttl_seconds: float):
        self.path = Path(path) if path else None
        self.idle_ttl = idle_ttl_seconds
        self._write_lock = threading.Lock()
        self.saves = 0  # successful writes, for tests and /health

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def is_expired(self, party: PartySession, now: float) -> bool:
        return now - party.last_active_at > self.idle_ttl

    def expire_idle(self, parties: dict[str, PartySession], now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        with STATE_LOCK:
            gone = [code for code, p in parties.items() if self.is_expired(p, now)]
            for code in gone:
                parties.pop(code, None)
        return gone

    def snapshot(self, parties: dict[str, PartySession]) -> str:
        with STATE_LOCK:
            rooms = {code: p.model_dump(mode="json", exclude=NOT_SAVED) for code, p in parties.items()}
        return json.dumps({"version": FORMAT_VERSION, "saved_at": time.time(), "parties": rooms})

    # What it does: writes every live party to one JSON file so a restart does not lose the room.
    # Catch it: "What happens if the server dies halfway through writing the file?"
    # Card: docs/cards/persistence-save.md
    def save(self, parties: dict[str, PartySession]) -> bool:
        if not self.enabled:
            return False
        # DECISION: one writer at a time, so an older snapshot never lands after a newer one
        with self._write_lock:
            # STEP: drop parties idle past the TTL
            self.expire_idle(parties)
            # STEP: snapshot under the state lock, tokens left out
            text = self.snapshot(parties)
            try:
                # STEP: write a temp file in the same directory and fsync it
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as f:
                        f.write(text)
                        f.flush()
                        os.fsync(f.fileno())
                    # STEP: atomic swap: readers see the old file or the new one, never half
                    os.replace(tmp, self.path)
                except BaseException:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    raise
            except OSError as e:
                # RETURN: a failed write keeps the app running from memory
                print(f"Room state save failed: {type(e).__name__}: {e}")
                return False
            self.saves += 1
            return True

    # What it does: reads the saved file on startup and rebuilds the live parties.
    # Catch it: "How do you restore state after a restart, and what if the file is bad?"
    # Card: docs/cards/persistence-load.md
    def load(self, now: float | None = None) -> dict[str, PartySession]:
        # DECISION: no file yet means a fresh start
        if not self.enabled or not self.path.exists():
            return {}
        now = time.time() if now is None else now
        # STEP: parse the whole file
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError) as e:
            # DECISION: an unreadable file is set aside as .corrupt, not deleted, and the app starts empty
            print(f"Room state load failed: {type(e).__name__}: {e}")
            with contextlib.suppress(OSError):
                os.replace(self.path, self.path.with_suffix(self.path.suffix + ".corrupt"))
            return {}
        parties: dict[str, PartySession] = {}
        # LOOP: validate each party on its own, so one bad record does not lose the rest
        for code, data in (raw.get("parties") or {}).items():
            try:
                p = PartySession.model_validate(data)
            except ValidationError:
                print(f"Room state: skipped invalid party {code!r}")
                continue
            # STEP: skip parties that went idle while the app was down
            if not self.is_expired(p, now):
                parties[code] = p
        # RETURN: live parties, ready to put in PARTIES
        return parties


def mutates(store_getter, parties: dict[str, PartySession]):
    """Decorator for sync endpoints that change state.

    Runs the endpoint under STATE_LOCK, marks the party active, then saves
    after the lock is released. The endpoint's signature is kept for FastAPI.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with STATE_LOCK:
                result = fn(*args, **kwargs)
                p = parties.get(kwargs.get("code", ""))
                if p is not None:
                    p.last_active_at = time.time()
            store_getter().save(parties)
            return result
        # FastAPI reads the signature to build the request model. The endpoint's
        # module uses string annotations, so resolve them against its globals here.
        wrapper.__signature__ = inspect.signature(fn, eval_str=True)
        return wrapper
    return deco
