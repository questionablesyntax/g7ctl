"""Which S6 scope (one of MainWindow's own per-page `DesiredDraft` ledgers)
a field path belongs to, and each scope's reader-facing name.

Qt-free on purpose: the watcher thread (escalation rule) and the widgets
(review sheet grouping, MainWindow dispatch) all need the same
classification, and the watcher shouldn't have to import a widget module
to get it.
"""
from __future__ import annotations

# Human scope labels -- the one place a scope string needs a
# reader-facing name rather than a dict key. Shared by ReviewSheet's own
# subtitle/section headers and MainWindow's write-action row/tooltips.
SCOPE_LABELS = {
    "vibration": "Vibration", "dock": "Dock (shared by every profile)",
    "triggers": "Triggers", "sticks": "Sticks", "motion": "Motion",
    "buttons": "Buttons", "profile_settings": "Profile Settings",
}


def scope_for_path(path: tuple) -> str | None:
    """Which scope a field path belongs to. Needed wherever code must
    dispatch on a bare path without already knowing which page it came
    from -- the review sheet's row grouping, MainWindow's per-row revert
    and multi-scope write-finish dispatch, and the watcher's own "is this
    a multi-scope batch" escalation check.

    Mirrors the exact path shapes each view's own `revert_path()`
    already guards on -- kept in sync with those by hand, same as the
    `_SETTING_FOR_SUFFIX`-style reverse maps in triggers_view.py/
    sticks_view.py/motion_view.py; there is no single registry a path's
    owning scope could be looked up from instead. Returns `None` for a
    path that doesn't match anything -- callers treat that as "nothing
    to do" rather than raising, same as every `revert_path()`'s own
    not-found case.
    """
    if not path:
        return None
    head = path[0]
    if head == "vibration":
        return "vibration"
    if head in ("dock_led_brightness", "dock_auto_on_off"):
        return "dock"
    if head == "triggers":
        return "triggers"
    if head == "sticks":
        return "sticks"
    if head == "motion":
        return "motion"
    if head == "buttons" or head in ("dpad_diagonal_lock", "swap_stick_dpad"):
        return "buttons"
    if head == "report_rate_hz":
        return "profile_settings"
    return None
