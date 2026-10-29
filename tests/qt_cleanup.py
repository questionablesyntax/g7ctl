"""Delete every top-level widget a test left behind, on that test's own turn.

Many GUI tests build a top-level widget (a MainWindow, a ButtonsView, a diagram)
and never close it, leaving the garbage collector to delete it whenever it next
runs. That can land in the middle of a *later* test's event loop, and on one
development machine it aborted the full suite intermittently: PyQt6 turns a
Python exception raised inside a Qt virtual into a hard abort, so the failure
showed up as a crash in whichever unrelated test happened to be running, not as
an ordinary assertion. Called after every test by tests/__init__.py.
"""


def destroy_top_level_widgets() -> None:
    try:
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication
    except ImportError:  # the pure-protocol tests need no Qt
        return
    app = QApplication.instance()
    if app is None:
        return
    widgets = app.topLevelWidgets()
    if not widgets:
        return
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
