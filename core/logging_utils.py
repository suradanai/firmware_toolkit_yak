"""Logging utilities to centralize logging configuration."""
from __future__ import annotations
import logging, os, pathlib, sys, datetime
from typing import Optional

LOG_DIR = pathlib.Path(os.environ.get('FW_LOG_DIR', 'logs'))
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / 'app.log'

def configure_logging(level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        return
    fmt = '%(asctime)s %(levelname)-7s %(name)s: %(message)s'
    datefmt = '%Y-%m-%dT%H:%M:%S'
    handlers = [
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)

class GuiLogger:
    """Adapter that writes to a QTextEdit-like append(str) object plus std logging."""
    def __init__(self, widget_append, name: str = 'gui'):
        self._append = widget_append
        self._logger = logging.getLogger(name)
    def __call__(self, msg: str):
        self._logger.info(msg)
        try:
            self._append(msg)
        except Exception:
            pass
