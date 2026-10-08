import os
import time
from pathlib import Path
from types import SimpleNamespace

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets

from riftlift.auth_browser import Browser
from riftlift.auth_ui import AuthDialog
from riftlift.config import Paths
from riftlift.util import RiftLiftError

LOGIN_URL = "https://auth.meta.com/native_sso/confirm?native_sso_etoken=abc"


def _paths(tmp_path: Path) -> Paths:
    paths = Paths(
        *(
            tmp_path / name
            for name in ("data", "cache", "config", "games", "prefix", "tools")
        )
    )
    paths.create()
    return paths


def _wait_until(app, condition, timeout: float = 2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _dialog(tmp_path, monkeypatch, *, browser, launch):
    monkeypatch.setattr("riftlift.auth_ui.QtCore.QTimer.singleShot", lambda *_: None)
    monkeypatch.setattr("riftlift.auth_ui.default_browser", browser)
    monkeypatch.setattr("riftlift.auth_ui.launch_browser_login", launch)
    session = SimpleNamespace(login_url=LOGIN_URL, callback_ready=lambda: False)
    monkeypatch.setattr(
        "riftlift.auth_ui.MetaAuthSession.begin", lambda _paths: session
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = AuthDialog(_paths(tmp_path))
    dialog.start()
    assert _wait_until(
        app, lambda: dialog.pending is not None and dialog.pending.done()
    )
    dialog.check_login()
    return app, dialog


def test_the_link_shows_even_when_the_browser_opened(tmp_path, monkeypatch) -> None:
    firefox = Browser("firefox", "Firefox", "firefox", ("firefox",))
    process = SimpleNamespace(poll=lambda: None)
    app, dialog = _dialog(
        tmp_path, monkeypatch, browser=lambda: firefox, launch=lambda *_: process
    )

    assert dialog.operation == "waiting"
    assert dialog.status.text() == "Waiting for Meta in Firefox…"
    assert dialog.link_section.isVisibleTo(dialog)
    assert dialog.link.text() == LOGIN_URL
    assert dialog.link.isReadOnly()
    dialog.close()
    app.processEvents()


def test_no_default_browser_still_offers_the_link(tmp_path, monkeypatch) -> None:
    def no_browser():
        raise RiftLiftError("could not detect the system default browser")

    launched = []
    app, dialog = _dialog(
        tmp_path, monkeypatch, browser=no_browser, launch=lambda *a: launched.append(a)
    )

    assert not launched
    assert dialog.operation == "waiting"
    assert dialog.timer.isActive()
    assert "No default browser was found" in dialog.status.text()
    assert dialog.link.text() == LOGIN_URL
    dialog.close()
    app.processEvents()


def test_a_browser_that_fails_to_start_leaves_the_link(tmp_path, monkeypatch) -> None:
    edge = Browser("edge", "Microsoft Edge", "chromium", ("edge",))

    def broken(*_args):
        raise OSError("no such file")

    app, dialog = _dialog(tmp_path, monkeypatch, browser=lambda: edge, launch=broken)

    assert dialog.operation == "waiting"
    assert "Could not open the browser" in dialog.status.text()
    assert dialog.link.text() == LOGIN_URL
    dialog.close()
    app.processEvents()


def test_copy_link_puts_it_on_the_clipboard(tmp_path, monkeypatch) -> None:
    app, dialog = _dialog(
        tmp_path,
        monkeypatch,
        browser=lambda: Browser("firefox", "Firefox", "firefox", ("firefox",)),
        launch=lambda *_: SimpleNamespace(poll=lambda: None),
    )

    dialog.copy_link.click()

    assert QtGui.QGuiApplication.clipboard().text() == LOGIN_URL
    assert dialog.copy_link.text() == "Copied"
    dialog._copied_timer.timeout.emit()
    assert dialog.copy_link.text() == "Copy link"
    dialog.close()
    app.processEvents()


def test_the_link_goes_away_on_cancel(tmp_path, monkeypatch) -> None:
    app, dialog = _dialog(
        tmp_path,
        monkeypatch,
        browser=lambda: Browser("firefox", "Firefox", "firefox", ("firefox",)),
        launch=lambda *_: SimpleNamespace(poll=lambda: None),
    )

    dialog.cancel_login()

    assert not dialog.link_section.isVisibleTo(dialog)
    assert dialog.link.text() == ""
    dialog.close()
    app.processEvents()


def test_wrapped_dialog_text_is_never_clipped(tmp_path, monkeypatch) -> None:
    def no_browser():
        raise RiftLiftError("could not detect the system default browser")

    monkeypatch.setattr("riftlift.auth_ui.QtCore.QTimer.singleShot", lambda *_: None)
    monkeypatch.setattr("riftlift.auth_ui.default_browser", no_browser)
    session = SimpleNamespace(login_url=LOGIN_URL, callback_ready=lambda: False)
    monkeypatch.setattr(
        "riftlift.auth_ui.MetaAuthSession.begin", lambda _paths: session
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = AuthDialog(_paths(tmp_path))
    # As in the app: the window is already open when the link arrives.
    dialog.show()
    app.processEvents()
    dialog.start()
    assert _wait_until(
        app, lambda: dialog.pending is not None and dialog.pending.done()
    )
    dialog.check_login()
    app.processEvents()

    for label in dialog.findChildren(QtWidgets.QLabel):
        if label.isVisible() and label.wordWrap():
            assert label.height() >= label.heightForWidth(label.width()), label.text()
    dialog.close()
    app.processEvents()
