from agent_harness import __version__


def test_package_version_is_initial_release() -> None:
    assert __version__ == "0.1.0"
