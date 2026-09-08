"""One loopback HTTP server alongside the Windows owner thread; no extra writer."""

import logging
import socket
import threading
import time

import uvicorn

from time_tracker.api.app import create_app
from time_tracker.api.commands import SettingsMailbox

logger = logging.getLogger(__name__)


class ApiServer:
    def __init__(self, runtime, *, port=8765):
        self.commands = SettingsMailbox(runtime)
        self.app = create_app(runtime.database, commands=self.commands, clock=runtime.clock)
        self.port = port
        self._socket = None
        self._thread = None
        self._error = None
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
                timeout_graceful_shutdown=3,
            )
        )

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._socket.bind(("127.0.0.1", self.port))
            self.port = self._socket.getsockname()[1]
            self._socket.listen(128)
            self._thread = threading.Thread(target=self._run, name="TimeTracker-API", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 10
            while not self._server.started:
                self.check()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Local API startup timed out")
                time.sleep(0.01)
        except BaseException:
            self.stop()
            raise
        logger.info("Local API listening at %s", self.url)

    def _run(self):
        try:
            self._server.run(sockets=[self._socket])
        except BaseException as error:
            self._error = error
            logger.exception("Local API stopped unexpectedly")

    def check(self):
        if self._thread is not None and not self._thread.is_alive():
            raise RuntimeError("Local API is no longer running") from self._error

    def tick(self):
        self.check()
        self.commands.drain()

    def stop(self):
        self.commands.close()
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                self._server.force_exit = True
                self._thread.join(timeout=2)
            self._thread = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
