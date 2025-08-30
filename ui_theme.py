"""Centralized UI theme and stylesheets for the Firmware Toolkit UI.

Provides a single get_stylesheet() function returning an application-wide
Qt stylesheet. Colors are chosen to be readable in both light/dark platforms.
"""
from __future__ import annotations

BTN_RADIUS = 6

THEMES = {
    # Dark (original)
    "dark": {
        "PRIMARY_BG": "#1e1e24", "PRIMARY_FG": "#f0f0f0",
        "ACCENT": "#2d7ff9", "ACCENT_ALT": "#f39c12", "DANGER": "#e74c3c", "SUCCESS": "#27ae60", "INFO": "#17a2b8",
        "FIELD_BG": "#262a31", "FIELD_BORDER": "#3a414d", "BTN_BASE": "#33363f", "BTN_BORDER": "#4a4f5c", "GROUP_BORDER": "#3a3a45", "MENU_BG": "#222", "TAB_BG": "#2b2f36", "TAB_BG_SEL": "#383d45", "SCROLL": "#444", "STATUS_BG": "#18181c"
    },
    # Light
    "light": {
        "PRIMARY_BG": "#fafafa", "PRIMARY_FG": "#222222",
        "ACCENT": "#1d6fed", "ACCENT_ALT": "#ffb347", "DANGER": "#d83a2e", "SUCCESS": "#1e874b", "INFO": "#0d7ea6",
        "FIELD_BG": "#ffffff", "FIELD_BORDER": "#cfd3d7", "BTN_BASE": "#f1f3f5", "BTN_BORDER": "#c5c9cc", "GROUP_BORDER": "#d0d4d8", "MENU_BG": "#ffffff", "TAB_BG": "#e9ecef", "TAB_BG_SEL": "#dde1e5", "SCROLL": "#b0b4b8", "STATUS_BG": "#eceff1"
    },
    # Gray / neutral
    "gray": {
        "PRIMARY_BG": "#2b2b2d", "PRIMARY_FG": "#ececec",
        "ACCENT": "#5c9ded", "ACCENT_ALT": "#e0a85c", "DANGER": "#e05d52", "SUCCESS": "#3fae72", "INFO": "#3aa0b9",
        "FIELD_BG": "#3a3a3d", "FIELD_BORDER": "#505055", "BTN_BASE": "#444447", "BTN_BORDER": "#5a5a5f", "GROUP_BORDER": "#55555a", "MENU_BG": "#333336", "TAB_BG": "#3c3c40", "TAB_BG_SEL": "#47474c", "SCROLL": "#606065", "STATUS_BG": "#222224"
    },
    # Soft blue
    "soft_blue": {
        "PRIMARY_BG": "#eef4fa", "PRIMARY_FG": "#203040",
        "ACCENT": "#3c7dd9", "ACCENT_ALT": "#f0a542", "DANGER": "#cc4d42", "SUCCESS": "#2f8f5a", "INFO": "#1f8fac",
        "FIELD_BG": "#ffffff", "FIELD_BORDER": "#b8c4d2", "BTN_BASE": "#dbe6f1", "BTN_BORDER": "#b3c0cc", "GROUP_BORDER": "#b7c3d0", "MENU_BG": "#ffffff", "TAB_BG": "#d2dfeb", "TAB_BG_SEL": "#c3d3e2", "SCROLL": "#a9b7c4", "STATUS_BG": "#d6e2ee"
    }
}

def available_themes():
    return list(THEMES.keys())

def build_stylesheet(p):
    return f"""
    QMainWindow {{ background: {p['PRIMARY_BG']}; color: {p['PRIMARY_FG']}; }}
    QWidget {{ color: {p['PRIMARY_FG']}; font-size: 13px; }}
    QGroupBox {{ border: 1px solid {p['GROUP_BORDER']}; border-radius: 6px; margin-top: 22px; padding: 18px 12px 14px 12px; font-weight: bold; }}
    QGroupBox:title {{ subcontrol-origin: margin; left: 14px; top: -12px; padding: 0px 8px; background: {p['PRIMARY_BG']}; border-radius: 6px; }}
    QPushButton {{ background: {p['BTN_BASE']}; border: 1px solid {p['BTN_BORDER']}; border-radius: {BTN_RADIUS}px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {p['ACCENT']}; }}
    QPushButton:pressed {{ background: {p['FIELD_BG']}; }}
    QPushButton[category="patch"] {{ background: {p['ACCENT']}; color: white; }}
    QPushButton[category="patch"]:hover {{ background: {shade(p['ACCENT'], -15)}; }}
    QPushButton[category="ai"] {{ background: {p['ACCENT_ALT']}; color: {('#222' if p['PRIMARY_BG']!='#fafafa' else '#222')}; font-weight: 600; }}
    QPushButton[category="ai"]:hover {{ background: {shade(p['ACCENT_ALT'], -12)}; }}
    QPushButton[category="danger"] {{ background: {p['DANGER']}; color: white; }}
    QPushButton[category="danger"]:hover {{ background: {shade(p['DANGER'], -12)}; }}
    QPushButton[category="ok"] {{ background: {p['SUCCESS']}; color: white; }}
    QPushButton[category="info"] {{ background: {p['INFO']}; color: white; }}
    QLineEdit, QComboBox, QTextEdit {{ background: {p['FIELD_BG']}; border: 1px solid {p['FIELD_BORDER']}; border-radius: 4px; selection-background-color: {p['ACCENT']}; }}
    QStatusBar {{ background: {p['STATUS_BG']}; color: {p['PRIMARY_FG']}; }}
    QMenuBar {{ background: {p['PRIMARY_BG']}; color: {p['PRIMARY_FG']}; }}
    QMenuBar::item:selected {{ background: {p['FIELD_BG']}; }}
    QMenu {{ background: {p['MENU_BG']}; color: {p['PRIMARY_FG']}; border: 1px solid {p['FIELD_BORDER']}; }}
    QMenu::item:selected {{ background: {p['ACCENT']}; color: white; }}
    QTabWidget::pane {{ border: 1px solid {p['FIELD_BORDER']}; }}
    QTabBar::tab {{ background: {p['TAB_BG']}; padding: 6px 14px; border: 1px solid {p['FIELD_BORDER']}; border-bottom: none; }}
    QTabBar::tab:selected {{ background: {p['TAB_BG_SEL']}; }}
    QScrollBar:vertical {{ background: {p['MENU_BG']}; width: 12px; }}
    QScrollBar::handle:vertical {{ background: {p['SCROLL']}; border-radius: 4px; min-height: 24px; }}
    QProgressBar {{ border: 1px solid {p['FIELD_BORDER']}; border-radius: 4px; text-align: center; background: {p['MENU_BG']}; color: {p['PRIMARY_FG']}; }}
    QProgressBar::chunk {{ background: {p['ACCENT']}; }}
    QMessageBox {{ background: {p['FIELD_BG']}; color: {p['PRIMARY_FG']}; }}
    QMessageBox QLabel {{ font-size: 14px; color: {p['PRIMARY_FG']}; }}
    """.strip()

def shade(hex_color: str, percent: int) -> str:
    """Lighten/darken hex color by percent (-100..100)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return '#' + hex_color
    r = int(hex_color[0:2],16); g=int(hex_color[2:4],16); b=int(hex_color[4:6],16)
    factor = (100 + percent) / 100
    r = max(0, min(255, int(r*factor)))
    g = max(0, min(255, int(g*factor)))
    b = max(0, min(255, int(b*factor)))
    return f"#{r:02x}{g:02x}{b:02x}"

def get_stylesheet(theme: str = "dark") -> str:
    p = THEMES.get(theme, THEMES['dark'])
    return build_stylesheet(p)
