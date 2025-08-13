"""
Centralized logging for imxup (GUI and CLI).

- Writes rolling log files under {central_store_base_path}/logs
- Supports daily rotation with compression and backup retention
- Normalizes incoming GUI log lines that already include HH:MM:SS timestamps
- Stores and reads settings from the main config file

Public API:
- get_logger(): AppLogger singleton
- AppLogger.log_to_file(message: str, level: int = logging.INFO)
- AppLogger.read_current_log() -> str
- AppLogger.get_logs_dir() -> str
- AppLogger.get_current_log_path() -> str
- AppLogger.update_settings(**kwargs)
- AppLogger.get_settings() -> dict
"""

from __future__ import annotations

import os
import re
import gzip
import shutil
import logging
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from typing import Optional, Dict, Any


_SINGLETON: Optional["AppLogger"] = None


def get_logger() -> "AppLogger":
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = AppLogger()
    return _SINGLETON


class _GzipTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Timed rotating handler that gzips rotated files when compress=True."""

    def __init__(self, filename: str, when: str, backupCount: int, encoding: str, compress: bool):
        super().__init__(filename, when=when, backupCount=backupCount, encoding=encoding, utc=False)
        self.compress = compress

    def rotate(self, source: str, dest: str) -> None:
        try:
            # Default rotate (rename)
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            os.replace(source, dest)
            if self.compress and os.path.exists(dest):
                gz_path = dest + ".gz"
                with open(dest, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                try:
                    os.remove(dest)
                except Exception:
                    pass
        except Exception:
            # Best-effort; do not crash the app on log rotation issues
            pass


class _GzipRotatingFileHandler(RotatingFileHandler):
    """Size-based rotating handler that gzips rotated files when compress=True."""

    def __init__(self, filename: str, maxBytes: int, backupCount: int, encoding: str, compress: bool):
        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding)
        self.compress = compress

    def rotate(self, source: str, dest: str) -> None:
        try:
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            os.replace(source, dest)
            if self.compress and os.path.exists(dest):
                gz_path = dest + ".gz"
                with open(dest, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                try:
                    os.remove(dest)
                except Exception:
                    pass
        except Exception:
            pass


class AppLogger:
    """Application-wide logger wrapper.

    Settings persisted in the main config file under section [LOGGING].
    """

    DEFAULTS = {
        "enabled": "true",
        "rotation": "daily",  # daily | size
        "backup_count": "7",
        "compress": "true",
        "max_bytes": "10485760",  # 10 MiB for size-based rotation
        "level_file": "INFO",
        "level_gui": "INFO",
        "filename": "imxup.log",
        # Category toggles (GUI and file sinks)
        "cats_gui_uploads": "true",
        "cats_file_uploads": "true",
        "cats_gui_auth": "true",
        "cats_file_auth": "true",
        "cats_gui_network": "true",
        "cats_file_network": "true",
        "cats_gui_ui": "true",
        "cats_file_ui": "true",
        "cats_gui_queue": "true",
        "cats_file_queue": "true",
        "cats_gui_renaming": "true",
        "cats_file_renaming": "true",
        "cats_gui_fileio": "true",
        "cats_file_fileio": "true",
        "cats_gui_general": "true",
        "cats_file_general": "true",
        # Upload success granularity preferences per sink
        # values: none | file | gallery | both
        "upload_success_mode_gui": "gallery",
        "upload_success_mode_file": "gallery",
    }

    TIME_ONLY_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+")

    LEVEL_MAP = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def __init__(self) -> None:
        # Lazy imports to avoid circular deps
        from imxup import get_config_path, get_central_store_base_path  # type: ignore
        self._get_config_path = get_config_path
        self._get_central_base = get_central_store_base_path

        self._logger = logging.getLogger("imxup")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self._file_handler: Optional[logging.Handler] = None
        self._file_formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        self._gui_level = logging.INFO
        self._file_level = logging.INFO

        self._settings = self._load_settings()
        self._apply_settings()

    def _load_settings(self) -> Dict[str, str]:
        import configparser
        cfg = configparser.ConfigParser()
        path = self._get_config_path()
        if os.path.exists(path):
            try:
                cfg.read(path)
            except Exception:
                pass
        if "LOGGING" not in cfg:
            return dict(self.DEFAULTS)
        data = dict(self.DEFAULTS)
        for k in self.DEFAULTS.keys():
            try:
                if k in cfg["LOGGING"]:
                    data[k] = cfg["LOGGING"][k]
            except Exception:
                continue
        return data

    def _save_settings(self) -> None:
        import configparser
        cfg = configparser.ConfigParser()
        path = self._get_config_path()
        if os.path.exists(path):
            try:
                cfg.read(path)
            except Exception:
                pass
        if "LOGGING" not in cfg:
            cfg["LOGGING"] = {}
        for k, v in self._settings.items():
            cfg["LOGGING"][k] = str(v)
        try:
            with open(path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def get_logs_dir(self) -> str:
        base = self._get_central_base()
        logs_dir = os.path.join(base, "logs")
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except Exception:
            pass
        return logs_dir

    def get_current_log_path(self) -> str:
        return os.path.join(self.get_logs_dir(), self._settings.get("filename", self.DEFAULTS["filename"]))

    def _ensure_file_handler(self) -> None:
        enabled = str(self._settings.get("enabled", "true")).lower() == "true"
        if not enabled:
            if self._file_handler is not None:
                try:
                    self._logger.removeHandler(self._file_handler)
                except Exception:
                    pass
                self._file_handler = None
            return

        log_path = self.get_current_log_path()
        rotation = (self._settings.get("rotation") or "daily").lower()
        backup_count = int(self._settings.get("backup_count", "7") or "7")
        compress = str(self._settings.get("compress", "true")).lower() == "true"
        max_bytes = int(self._settings.get("max_bytes", "10485760") or "10485760")

        # Rebuild handler if it is missing or configuration changed (simpler: always rebuild)
        if self._file_handler is not None:
            try:
                self._logger.removeHandler(self._file_handler)
            except Exception:
                pass
            self._file_handler = None

        try:
            if rotation == "size":
                handler = _GzipRotatingFileHandler(
                    filename=log_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                    compress=compress,
                )
            else:
                handler = _GzipTimedRotatingFileHandler(
                    filename=log_path,
                    when="midnight",
                    backupCount=backup_count,
                    encoding="utf-8",
                    compress=compress,
                )
            handler.setLevel(self._file_level)
            handler.setFormatter(self._file_formatter)
            self._logger.addHandler(handler)
            self._file_handler = handler
        except Exception:
            # Do not crash on handler setup failures
            self._file_handler = None

    def _apply_settings(self) -> None:
        self._file_level = self.LEVEL_MAP.get(self._settings.get("level_file", "INFO"), logging.INFO)
        self._gui_level = self.LEVEL_MAP.get(self._settings.get("level_gui", "INFO"), logging.INFO)
        self._ensure_file_handler()

    def update_settings(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if k in self.DEFAULTS:
                self._settings[k] = str(v)
        self._save_settings()
        self._apply_settings()

    def get_settings(self) -> Dict[str, Any]:
        # Return a copy with normalized types
        s = dict(self._settings)
        s["enabled"] = str(s.get("enabled", "true")).lower() == "true"
        s["compress"] = str(s.get("compress", "true")).lower() == "true"
        try:
            s["backup_count"] = int(s.get("backup_count", 7))
        except Exception:
            s["backup_count"] = 7
        try:
            s["max_bytes"] = int(s.get("max_bytes", 10485760))
        except Exception:
            s["max_bytes"] = 10485760
        # Normalize categories
        for cat in ("uploads","auth","network","ui","queue","renaming","fileio","general"):
            for sink in ("gui","file"):
                key = f"cats_{sink}_{cat}"
                s[key] = str(s.get(key, "true")).lower() == "true"
        # Normalize modes
        for sink in ("gui","file"):
            key = f"upload_success_mode_{sink}"
            val = str(s.get(key, "gallery")).lower()
            if val not in ("none","file","gallery","both"):
                val = "gallery"
            s[key] = val
        return s

    @classmethod
    def _strip_leading_time(cls, message: str) -> str:
        # If message starts with HH:MM:SS, remove it; file formatter will add date+time
        try:
            return cls.TIME_ONLY_RE.sub("", message, count=1)
        except Exception:
            return message

    def should_emit_gui(self, category: str, level: int) -> bool:
        try:
            if level < self._gui_level:
                return False
        except Exception:
            pass
        cat_key = f"cats_gui_{category.lower()}"
        cats = self.get_settings()
        return bool(cats.get(cat_key, True))

    def should_emit_file(self, category: str, level: int) -> bool:
        enabled = str(self._settings.get("enabled", "true")).lower() == "true"
        if not enabled:
            return False
        try:
            if level < self._file_level:
                return False
        except Exception:
            pass
        cat_key = f"cats_file_{category.lower()}"
        cats = self.get_settings()
        return bool(cats.get(cat_key, True))

    def should_log_upload_file_success(self, target: str) -> bool:
        # target: 'gui' or 'file'
        mode = str(self._settings.get(f"upload_success_mode_{target}", "gallery")).lower()
        return mode in ("file", "both")

    def should_log_upload_gallery_success(self, target: str) -> bool:
        mode = str(self._settings.get(f"upload_success_mode_{target}", "gallery")).lower()
        return mode in ("gallery", "both")

    def log_to_file(self, message: str, level: int = logging.INFO, category: str = "general") -> None:
        # Respect file level and enabled flag
        enabled = str(self._settings.get("enabled", "true")).lower() == "true"
        if not enabled:
            return
        try:
            if level < self._file_level:
                return
        except Exception:
            pass
        # Category gating
        if not self.should_emit_file(category, level):
            return
        if not self._logger:
            return
        try:
            normalized = self._strip_leading_time(message)
            self._logger.log(level, normalized)
        except Exception:
            pass

    def read_current_log(self, tail_bytes: Optional[int] = None) -> str:
        path = self.get_current_log_path()
        if not os.path.exists(path):
            return ""
        try:
            if tail_bytes and tail_bytes > 0:
                # Efficient tail read
                size = os.path.getsize(path)
                with open(path, "rb") as f:
                    if size > tail_bytes:
                        f.seek(-tail_bytes, os.SEEK_END)
                    data = f.read()
                return data.decode("utf-8", errors="replace")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""


