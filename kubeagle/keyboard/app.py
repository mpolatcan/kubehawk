"""App-level keyboard bindings.

This module contains Textual Binding objects for app-level bindings
that work from any screen.
"""

from textual.binding import Binding

# ============================================================================
# Textual Binding objects for app-level bindings
# ============================================================================

APP_BINDINGS: list[Binding] = [
    Binding("escape", "back", "Back", priority=True),
    Binding("h", "nav_home", "Summary"),
    Binding("c", "nav_cluster", "Cluster"),
    Binding("C", "nav_charts", "Charts"),
    Binding("e", "nav_export", "Export"),
    Binding("ctrl+s", "nav_settings", "Settings"),
    Binding("R", "nav_recommendations", "Viol+Recs"),
    Binding("?", "show_help", "Help"),
    Binding("r", "refresh", "Refresh"),
    Binding("q", "app.quit", "Quit", priority=True),
]

__all__ = [
    "APP_BINDINGS",
]
