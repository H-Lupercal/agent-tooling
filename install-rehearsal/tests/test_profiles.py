from pathlib import Path

import pytest

from install_rehearsal.profiles import build_profile, windows_home_parts


def test_linux_profile_redirects_xdg_paths(tmp_path: Path) -> None:
    profile = build_profile("linux", tmp_path)

    assert profile.environment["HOME"] == str(tmp_path)
    assert profile.environment["XDG_CONFIG_HOME"] == str(tmp_path / ".config")
    assert profile.coverage_label == "redirected-user-profile"


def test_macos_profile_redirects_home_and_temporary_directory(tmp_path: Path) -> None:
    profile = build_profile("darwin", tmp_path)

    assert profile.environment["HOME"] == str(tmp_path)
    assert profile.environment["TMPDIR"] == str(tmp_path / "tmp")


def test_windows_profile_redirects_appdata(tmp_path: Path) -> None:
    profile = build_profile("win32", tmp_path)

    assert profile.environment["USERPROFILE"] == str(tmp_path)
    assert profile.environment["APPDATA"] == str(tmp_path / "AppData" / "Roaming")
    assert profile.environment["LOCALAPPDATA"] == str(tmp_path / "AppData" / "Local")


def test_unsupported_platform_has_stable_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UNSUPPORTED_PLATFORM"):
        build_profile("plan9", tmp_path)


def test_windows_home_parts_do_not_duplicate_drive() -> None:
    assert windows_home_parts(r"C:\Users\Neil") == ("C:", r"\Users\Neil")
