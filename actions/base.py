from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any, Dict, Optional


@dataclass
class AppContext:
    """Lightweight dependency container passed to actions.

    Only include objects actually used by actions to avoid tight coupling.
    Attributes are populated in MainWindow right before action execution.
    """

    window: Any  # MainWindow instance
    logger: Callable[[str], None]
    status: Callable[[str], None]

    # Common backend capabilities (callables or methods bound on window)
    scan_env: Optional[Callable[[], None]] = None
    patch_bootdelay: Optional[Callable[[int], None]] = None
    open_env_editor: Optional[Callable[[], None]] = None
    open_rootfs_editor: Optional[Callable[[], None]] = None
    run_selective_patch: Optional[Callable[[], None]] = None
    run_network_tools: Optional[Callable[[], None]] = None
    run_serial_shell: Optional[Callable[[], None]] = None
    run_custom_script: Optional[Callable[[], None]] = None

    extra: Dict[str, Any] = None

    def get(self, key: str, default: Any = None) -> Any:
        if not self.extra:
            return default
        return self.extra.get(key, default)


class ActionError(Exception):
    pass


class BaseAction:
    """Abstract base class for user-triggered actions.

    Subclasses implement run(ctx) and may optionally override is_enabled(ctx).
    """

    action_id: str = "base"
    text: str = "Base Action"
    tooltip: str = ""

    def is_enabled(self, ctx: AppContext) -> bool:
        return True

    def run(self, ctx: AppContext):  # pragma: no cover - interface
        raise NotImplementedError


class SimpleCallbackAction(BaseAction):
    """Wrap a plain callable into an Action object."""

    def __init__(self, action_id: str, text: str, callback: Callable[[AppContext], None], tooltip: str = ""):
        self.action_id = action_id
        self.text = text
        self._callback = callback
        self.tooltip = tooltip

    def run(self, ctx: AppContext):
        self._callback(ctx)
