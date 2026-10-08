from pathlib import Path

import pytest
from meta_pcvr_downloader.api import Build

from riftlift.builds import AvailableBuild, merge_builds
from riftlift.config import Paths


def _paths(tmp_path: Path) -> Paths:
    paths = Paths(
        tmp_path / "data",
        tmp_path / "cache",
        tmp_path / "config",
        tmp_path / "games",
        tmp_path / "prefix",
        tmp_path / "tools",
    )
    paths.create()
    return paths


def _pe64(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(0x200)
    header[:2] = b"MZ"
    header[0x3C:0x40] = (0x80).to_bytes(4, "little")
    header[0x80:0x84] = b"PE\0\0"
    header[0x84:0x86] = (0x8664).to_bytes(2, "little")
    path.write_bytes(bytes(header))


def test_the_default_install_stays_on_the_build_meta_offers() -> None:
    from riftlift.builds import default_build

    offered = Build("1", "Bigscreen", "live", "0.950.2.03f010", 3451)
    history = [
        AvailableBuild(
            "1", "Bigscreen", "alpha", "0.950.2.a276a2", 3452, channels=("PCALPHA",)
        ),
        AvailableBuild(
            "1", "Bigscreen", "live", "0.950.2.03f010", 3451, channels=("LIVE",)
        ),
    ]

    builds = merge_builds([offered], history)

    # The alpha build is newer and stays installable, but only when chosen.
    assert [build.binary_id for build in builds] == ["alpha", "live"]
    assert default_build(builds).binary_id == "live"
    assert default_build([offered]).binary_id == "live"


def test_a_plain_install_downloads_the_offered_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from riftlift import library

    paths = _paths(tmp_path)
    builds = merge_builds(
        [Build("1", "Game", "live", "1.0", 10)],
        [AvailableBuild("1", "Game", "beta", "1.1", 11, channels=("BETA",))],
    )
    downloaded = []
    monkeypatch.setattr(library, "account_tokens", lambda *_args: ["token"])
    monkeypatch.setattr(
        library, "fetch_manifest", lambda _t, build: {"launchFile": "a.exe"}
    )
    monkeypatch.setattr(library, "populate_game_metadata", lambda *_args: None)

    class Downloader:
        def __init__(self, _token, build, directory, _cache, _workers):
            downloaded.append(build.binary_id)
            self.directory = directory

        def run(self, _manifest):
            _pe64(self.directory / "a.exe")

    monkeypatch.setattr(library, "Downloader", Downloader)

    game = library.add(paths, "1", builds=builds)

    assert downloaded == ["live"]
    assert game.binary_id == "live"


@pytest.fixture
def app():
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_the_picker_offers_the_default_build_first(app, tmp_path: Path) -> None:
    from riftlift.game_ui import StoreGameDialog

    dialog = StoreGameDialog(_paths(tmp_path), lambda: None)
    dialog._set_builds(
        merge_builds(
            [Build("1", "Game", "live", "1.0", 10)],
            [AvailableBuild("1", "Game", "beta", "1.1", 11, channels=("BETA",))],
        )
    )

    items = [
        (dialog.versions.itemText(i), dialog.versions.itemData(i))
        for i in range(dialog.versions.count())
    ]
    assert items == [
        ("1.0 (10) (latest)", None),
        ("1.1 (11) · BETA", "beta"),
        ("All versions (2)", "all"),
    ]
    dialog.close()


def _record(paths: Path, slug: str, version: str, binary_id: str) -> None:
    from riftlift.config import Game

    Game(
        slug,
        f"Game ({version})",
        "1",
        "k",
        str(paths.games / slug),
        "a.exe",
        [],
        version=version,
        source="meta",
        binary_id=binary_id,
    ).save(paths)


def test_a_chosen_version_keeps_out_of_another_builds_paused_folder(
    tmp_path: Path,
) -> None:
    from riftlift.library import BUILD_MARKER, _install_identity

    paths = _paths(tmp_path)
    paused = paths.games / "game"
    paused.mkdir(parents=True)
    (paused / BUILD_MARKER).write_text("other\n")
    chosen = Build("1", "Game", "chosen", "2.0", 20)

    assert _install_identity(paths, chosen, side_by_side=True) == (
        "game-2-0",
        "Game (2.0)",
    )
    # The paused build itself still resumes into its folder.
    paused_build = Build("1", "Game", "other", "1.0", 10)
    assert _install_identity(paths, paused_build, side_by_side=True)[0] == "game"


def test_the_build_code_fallback_never_lands_on_another_version(tmp_path: Path) -> None:
    from riftlift.library import _install_identity

    paths = _paths(tmp_path)
    _record(paths, "game", "3.0", "b30")
    _record(paths, "game-1-0-2", "1.0.2", "b102")
    _record(paths, "game-1-0", "1.0", "b10")
    # "1.0" with build code 2 would fall back to game-1-0-2, version 1.0.2's folder.
    second = Build("1", "Game", "b2", "1.0", 2)

    slug, name = _install_identity(paths, second, side_by_side=True)

    assert slug not in {"game", "game-1-0", "game-1-0-2"}
    assert name == "Game (1.0, build 2)"
    assert _install_identity(paths, second, side_by_side=True)[0] == slug
