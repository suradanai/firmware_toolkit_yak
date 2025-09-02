"""External menu structure configuration.

Each entry is a dict with optional keys:
  - id: action registry key (leaf items)
  - label: visible text
  - children: nested list for submenus
  - separator: bool (if True, acts as menu separator)

Top level constant MENU_STRUCTURE is consumed by MainWindow to build menus.
Icons: ACTION_ICONS maps action ids to icon filenames (relative to icons/).
"""

MENU_STRUCTURE = [
    {  # U-Boot / Environment related
        "label": "U-Boot",
        "children": [
            {"id": "boot_delay_picker", "label": "Boot Delay (Auto Patch)"},
            {"id": "env_scan", "label": "Scan Environment"},
            {"id": "env_editor", "label": "Open Environment Editor"},
            {"separator": True},
            {"id": "boot_delay_set_0", "label": "Set bootdelay=0"},
            {"id": "boot_delay_set_3", "label": "Set bootdelay=3"},
            {"id": "boot_delay_set_5", "label": "Set bootdelay=5"},
        ],
    },
    {  # Filesystem / RootFS
        "label": "RootFS",
        "children": [
            {"id": "rootfs_editor", "label": "Open RootFS Editor"},
            {"id": "multi_squash_dryrun", "label": "Multi-Squash Dry Run"},
            {"id": "multi_squash_apply", "label": "Multi-Squash Apply"},
        ],
    },
    {  # Patching / Selective
        "label": "Patching",
        "children": [
            {"id": "selective_patch", "label": "Selective Patch"},
            {"id": "auto_run_mode", "label": "Auto Run Mode"},
        ],
    },
    {  # Tools / Misc
        "label": "Tools",
        "children": [
            {"id": "serial_shell", "label": "Serial Shell"},
            {"id": "network_tools", "label": "Network Tools"},
            {"id": "archive_outputs", "label": "Archive Outputs"},
            {"id": "custom_script", "label": "Run Custom Script"},
        ],
    },
]


ACTION_ICONS = {
    "boot_delay_picker": "timer.svg",
    "boot_delay_set_0": "timer.svg",
    "boot_delay_set_3": "timer.svg",
    "boot_delay_set_5": "timer.svg",
    "env_scan": "search.svg",
    "env_editor": "edit.svg",
    "rootfs_editor": "filesystem.svg",
    "multi_squash_dryrun": "layers.svg",
    "multi_squash_apply": "apply.svg",
    "selective_patch": "target.svg",
    "auto_run_mode": "automation.svg",
    "serial_shell": "terminal.svg",
    "network_tools": "network.svg",
    "archive_outputs": "archive.svg",
    "custom_script": "script.svg",
}
