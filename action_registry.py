"""Central action registry creation.

This module builds a dictionary mapping action_id -> Action instance.
The MainWindow will supply an AppContext at run time.
"""

from typing import Dict

from actions.base import BaseAction, SimpleCallbackAction, AppContext
from actions.boot_delay import BootDelayPickerAction, BootDelayQuickSetAction


def build_registry(window) -> Dict[str, BaseAction]:
    """Create and return all action instances.

    The window object is passed only if an action wants to bind early, but
    actions should prefer using the runtime AppContext when run() is invoked.
    """

    registry: Dict[str, BaseAction] = {}

    # Boot delay actions
    registry["boot_delay_picker"] = BootDelayPickerAction()
    for val in (0, 3, 5):
        act = BootDelayQuickSetAction(val)
        registry[act.action_id] = act

    # Environment scan/editor (callback wrappers; methods expected on window)
    registry["env_scan"] = SimpleCallbackAction(
        "env_scan", "Scan Environment", lambda ctx: getattr(ctx.window, "_special_env_scan_wrapper", ctx.logger)( )  # type: ignore
    )
    registry["env_editor"] = SimpleCallbackAction(
        "env_editor", "Open Environment Editor", lambda ctx: getattr(ctx.window, "open_uboot_env_editor_dialog", ctx.logger)()
    )

    # RootFS
    registry["rootfs_editor"] = SimpleCallbackAction(
        "rootfs_editor", "Open RootFS Editor", lambda ctx: getattr(ctx.window, "open_rootfs_editor_dialog", ctx.logger)()
    )
    registry["multi_squash_dryrun"] = SimpleCallbackAction(
        "multi_squash_dryrun", "Multi-Squash Dry Run", lambda ctx: getattr(ctx.window, "multi_squash_dryrun", ctx.logger)()
    )
    registry["multi_squash_apply"] = SimpleCallbackAction(
        "multi_squash_apply", "Multi-Squash Apply", lambda ctx: getattr(ctx.window, "multi_squash_apply", ctx.logger)()
    )

    # Patching
    registry["selective_patch"] = SimpleCallbackAction(
        "selective_patch", "Selective Patch", lambda ctx: getattr(ctx.window, "open_selective_patch_dialog", ctx.logger)()
    )
    registry["auto_run_mode"] = SimpleCallbackAction(
        "auto_run_mode", "Auto Run Mode", lambda ctx: getattr(ctx.window, "auto_run_mode", ctx.logger)()
    )

    # Tools / Misc
    registry["serial_shell"] = SimpleCallbackAction(
        "serial_shell", "Serial Shell", lambda ctx: getattr(ctx.window, "open_serial_shell_dialog", ctx.logger)()
    )
    registry["network_tools"] = SimpleCallbackAction(
        "network_tools", "Network Tools", lambda ctx: getattr(ctx.window, "open_network_tools_dialog", ctx.logger)()
    )
    registry["archive_outputs"] = SimpleCallbackAction(
        "archive_outputs", "Archive Outputs", lambda ctx: getattr(ctx.window, "archive_outputs", ctx.logger)()
    )
    registry["custom_script"] = SimpleCallbackAction(
        "custom_script", "Run Custom Script", lambda ctx: getattr(ctx.window, "run_custom_script", ctx.logger)()
    )

    return registry
