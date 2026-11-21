"""Thread-safe helpers shared by the processing core and the HTTP server."""
import json
import queue
import threading
import time


class FrameHub:
    """Keeps the latest encoded preview frame and wakes up every connected stream."""

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self._jpeg = b''
        self._size = (0, 0)
        self._clients = 0
        self.on_change = None

    def _changed(self):
        cb = self.on_change
        if cb:
            try:
                cb(self._seq)
            except Exception:  # pylint: disable=broad-except
                pass

    def publish(self, jpeg: bytes, width: int = 0, height: int = 0):
        with self._cond:
            self._seq += 1
            self._jpeg = jpeg
            self._size = (width, height)
            self._cond.notify_all()
        self._changed()

    def clear(self):
        with self._cond:
            self._seq += 1
            self._jpeg = b''
            self._size = (0, 0)
            self._cond.notify_all()
        self._changed()

    @property
    def seq(self):
        return self._seq

    @property
    def size(self):
        return self._size

    def latest(self):
        with self._cond:
            return self._seq, self._jpeg

    def wait_next(self, last_seq, timeout=10.0):
        """Block until a frame newer than last_seq exists. Returns (seq, jpeg) or None on timeout."""
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            if self._seq == last_seq:
                return None
            return self._seq, self._jpeg

    def client_connected(self):
        with self._cond:
            self._clients += 1

    def client_disconnected(self):
        with self._cond:
            self._clients = max(0, self._clients - 1)

    @property
    def clients(self):
        return self._clients


class EventBus:
    """Fan-out of small JSON events (server-sent events) to every browser tab."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subs = set()
        self._last_player_emit = 0.0

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event_type: str, **data):
        payload = json.dumps({'type': event_type, **data}, default=str)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:  # drop the oldest event, never block the processing threads
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

    def publish_throttled(self, event_type: str, min_interval=0.06, **data):
        now = time.monotonic()
        if now - self._last_player_emit >= min_interval:
            self._last_player_emit = now
            self.publish(event_type, **data)


class Signal:
    """Minimal stand-in for the old GUI signals used by the processing core (`.emit(...)`)."""

    def __init__(self, handler=None):
        self._handler = handler

    def emit(self, *args):
        if self._handler:
            try:
                self._handler(*args)
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"Signal handler error: {e}")
