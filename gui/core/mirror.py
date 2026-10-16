"""
Signyales GUI — mirror link: the Pi shares recognized words with a laptop.

The Pi (server) sends one JSON object per line over TCP to every connected
laptop (client). The laptop shows the subtitle and plays the sound. Only
events are sent (recognized words and a twice-a-second status), never raw
sensor data or recordings.

Meant for a cable or a private network between your own two machines: there
is no password, so don't turn sharing on while connected to a public network.

No Tk imports.
"""

import json
import socket
import threading

DEFAULT_PORT = 50555
SHARED_TYPES = ("started", "status", "gesture", "stopped", "error")


def local_ip_addresses():
    """Best-effort list of this machine's IPv4 addresses, without needing internet."""
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    for probe in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))       # UDP connect sends nothing
                addrs.add(s.getsockname()[0])
        except OSError:
            pass
    addrs.discard("0.0.0.0")
    return sorted(a for a in addrs if not a.startswith("127.")) or ["127.0.0.1"]


class MirrorServer:
    def __init__(self, host="0.0.0.0", port=DEFAULT_PORT, on_clients_changed=None):
        self.host, self.port = host, port
        self._on_clients_changed = on_clients_changed or (lambda n: None)
        self._clients = []
        self._lock = threading.Lock()
        self._sock = None
        self._running = False
        self._last_started = None    # replayed to laptops that connect later

    @property
    def client_count(self):
        with self._lock:
            return len(self._clients)

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(4)
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                if self._last_started is not None:
                    try:
                        conn.sendall((json.dumps(self._last_started) + "\n").encode())
                    except OSError:
                        conn.close()
                        continue
                self._clients.append(conn)
            self._on_clients_changed(self.client_count)

    def publish(self, event: dict):
        if event.get("type") not in SHARED_TYPES:
            return
        if event["type"] == "started":
            self._last_started = event
        elif event["type"] == "stopped":
            self._last_started = None
        data = (json.dumps(event) + "\n").encode()
        dead = []
        with self._lock:
            for c in self._clients:
                try:
                    c.sendall(data)
                except OSError:
                    dead.append(c)
            for c in dead:
                self._clients.remove(c)
                c.close()
        if dead:
            self._on_clients_changed(self.client_count)

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        with self._lock:
            for c in self._clients:
                c.close()
            self._clients.clear()


class MirrorClient:
    def __init__(self, on_event, on_disconnect=None):
        self._on_event = on_event
        self._on_disconnect = on_disconnect or (lambda reason: None)
        self._sock = None
        self._closing = False

    def connect(self, host, port=DEFAULT_PORT, timeout=5.0):
        """Raises OSError if the Pi can't be reached."""
        self._closing = False
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(None)
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        reason = "closed by the Pi"
        try:
            with self._sock.makefile("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        self._on_event(json.loads(line))
                    except ValueError:
                        continue
        except OSError as exc:
            reason = str(exc)
        if not self._closing:
            self._on_disconnect(reason)

    def close(self):
        self._closing = True
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
