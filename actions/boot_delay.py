from __future__ import annotations

from .base import BaseAction, AppContext


class BootDelayPickerAction(BaseAction):
    action_id = "boot_delay_picker"
    text = "Boot Delay (0-9)"
    tooltip = "Open quick boot delay picker and auto-patch"

    def run(self, ctx: AppContext):
        # Delegates to existing MainWindow method if present
        picker = getattr(ctx.window, "show_boot_delay_picker", None)
        if picker:
            picker()
        else:
            ctx.logger("Boot delay picker not available in this build.")


class BootDelayQuickSetAction(BaseAction):
    """Directly set a concrete bootdelay value without showing the picker.

    Instances for common values can be registered (e.g., via menu or shortcuts).
    """

    def __init__(self, value: int):
        self.value = value
        self.action_id = f"boot_delay_set_{value}"
        self.text = f"Set bootdelay = {value}"
        self.tooltip = f"Patch bootdelay to {value} immediately"

    def run(self, ctx: AppContext):
        if ctx.patch_bootdelay:
            ctx.patch_bootdelay(self.value)
        else:
            # Fallback: try window method
            method = getattr(ctx.window, "_auto_patch_bootdelay", None)
            if method:
                method(self.value)
            else:
                ctx.logger("Boot delay patch method not available.")
