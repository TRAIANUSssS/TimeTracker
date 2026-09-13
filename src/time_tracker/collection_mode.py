"""Persistent collection preference and asynchronous explicit component setup."""

import json
import logging
import os
import secrets
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class CollectionMode:
    def __init__(self, database_path, backend, *, external=False):
        self.path = Path(database_path).with_name("collection-settings.json")
        self.backend = backend
        self.external = external
        self.token = secrets.token_urlsafe(32)
        self._lock = threading.RLock()
        self._busy = False
        self._error = None
        self._check_error = None
        self._closed = False
        self.source = None
        self._desired = "polling"
        try:
            if self.path.exists():
                settings = json.loads(self.path.read_text(encoding="utf-8"))
                if settings != {"version": 1, "mode": settings.get("mode")} or settings[
                    "mode"
                ] not in ("polling", "etw"):
                    raise ValueError("Invalid collection settings")
                self._desired = settings["mode"]
        except (OSError, ValueError, AttributeError, TypeError):
            logger.warning("Cannot read collection settings; using polling", exc_info=True)
            self._error = "Не удалось прочитать настройки сбора. Используется обычный режим."
        self.active_mode = "external" if external else self._desired

    def _save(self, mode):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "mode": mode}), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self._desired = mode

    def status(self):
        try:
            installed = self.backend.installed()
            setup_error = None
            with self._lock:
                self._check_error = None
        except Exception as error:
            installed = False
            setup_error = "Не удалось проверить фоновый компонент Windows."
            with self._lock:
                failure = (type(error).__name__, str(error))
                if failure != self._check_error:
                    logger.warning("Cannot verify installed ETW component", exc_info=True)
                    self._check_error = failure
        with self._lock:
            healthy = self.source is not None and self.source.status()["healthy"]
            return {
                "mode": self._desired,
                "active_mode": self.active_mode,
                "effective_mode": "etw" if healthy else "polling",
                "installed": installed,
                "can_install": self.backend.available(),
                "busy": self._busy,
                "error": self._error or setup_error,
                "restart_required": not self.external and self._desired != self.active_mode,
                "external": self.external,
                "token": self.token,
            }

    def request(self, action):
        with self._lock:
            if self._closed or self._busy or self.external:
                raise RuntimeError("Настройки сейчас недоступны.")
            if action not in ("polling", "etw", "install", "remove"):
                raise ValueError("Неизвестное действие.")
            if action in ("install", "remove") and self.active_mode == "etw":
                raise RuntimeError("Сначала выберите обычный режим и перезапустите приложение.")
            if action == "etw":
                try:
                    installed = self.backend.installed()
                except Exception as error:
                    raise RuntimeError(
                        "Не удалось проверить компонент. Попробуйте восстановить его."
                    ) from error
                if not installed:
                    raise RuntimeError("Сначала установите фоновый компонент.")
            self._error = None
            if action in ("polling", "etw"):
                self._save(action)
                return
            self._busy = True
            threading.Thread(
                target=self._setup, args=(action,), name="TimeTracker-ETW-Setup", daemon=True
            ).start()

    def _setup(self, action):
        try:
            self.backend.configure(action)
            with self._lock:
                # Installation does not switch an in-flight run. Next launch reads the preference.
                self._save("etw" if action == "install" else "polling")
        except Exception as error:
            logger.warning("ETW component setup failed", exc_info=True)
            with self._lock:
                self._error = str(error)
        finally:
            with self._lock:
                self._busy = False

    def close(self):
        with self._lock:
            self._closed = True
