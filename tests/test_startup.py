from __future__ import annotations

import argparse

from pournotify.config import AppConfig
from pournotify.main import build_parser, launch_action
from pournotify.services.startup import (
    RUN_KEY,
    VALUE_NAME,
    legacy_startup_entries,
    migrate_legacy_startup_entries,
    set_startup_enabled,
    startup_command,
)


class RegistryKey:
    def __init__(self, registry):
        self.registry = registry

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.write_count = 0

    def OpenKey(self, root, path, *args):
        assert root is self.HKEY_CURRENT_USER
        assert path == RUN_KEY
        return RegistryKey(self)

    def CreateKeyEx(self, root, path, *args):
        return self.OpenKey(root, path)

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value
        self.write_count += 1

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def args(*, notify=None, observe_notify=None, background=False):
    return argparse.Namespace(
        notify=notify,
        observe_notify=observe_notify,
        background=background,
    )


def test_parser_accepts_explicit_background_mode():
    parsed = build_parser().parse_args(["--background"])
    assert parsed.background is True
    assert parsed.notify is None
    assert parsed.observe_notify is None


def test_parser_accepts_observation_mode():
    parsed = build_parser().parse_args(["--observe-notify", '{"type":"example"}'])

    assert parsed.observe_notify == '{"type":"example"}'
    assert parsed.notify is None
    assert parsed.background is False


def test_background_and_manual_launch_choose_expected_resident_action(monkeypatch):
    controls = []
    monkeypatch.setattr("pournotify.main.send_to_running_instance", lambda payload: False)
    monkeypatch.setattr(
        "pournotify.main.send_control_to_running_instance",
        lambda command: controls.append(command) or False,
    )

    assert launch_action(args(background=True)) == "background"
    assert launch_action(args()) == "show"
    assert controls == ["ping", "show"]


def test_existing_resident_exits_for_background_and_shows_for_manual(monkeypatch):
    controls = []
    monkeypatch.setattr("pournotify.main.send_to_running_instance", lambda payload: False)
    monkeypatch.setattr(
        "pournotify.main.send_control_to_running_instance",
        lambda command: controls.append(command) or True,
    )

    assert launch_action(args(background=True)) == "exit"
    assert launch_action(args()) == "exit"
    assert controls == ["ping", "show"]


def test_notification_invocation_keeps_payload_forwarding(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        "pournotify.main.send_to_running_instance",
        lambda payload: payloads.append(payload) or True,
    )
    monkeypatch.setattr(
        "pournotify.main.send_control_to_running_instance",
        lambda command: (_ for _ in ()).throw(AssertionError(command)),
    )

    payload = '{"type":"agent-turn-complete"}'
    assert launch_action(args(notify=payload)) == "exit"
    assert payloads == [payload]


def test_observation_invocation_uses_observation_channel(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        "pournotify.main.send_observation_to_running_instance",
        lambda payload: payloads.append(payload) or True,
    )
    monkeypatch.setattr(
        "pournotify.main.send_to_running_instance",
        lambda payload: (_ for _ in ()).throw(AssertionError(payload)),
    )

    payload = '{"type":"agent-turn-complete"}'
    assert launch_action(args(observe_notify=payload)) == "exit"
    assert payloads == [payload]


def test_startup_command_quotes_paths_with_spaces_and_non_ascii(tmp_path):
    executable = tmp_path / "Pour Notify 文档" / "PourNotify.exe"
    command = startup_command(executable)
    assert command == f'"{executable.resolve()}" --background'


def test_enabling_updates_one_entry_without_duplicates_and_disabling_removes_it(tmp_path):
    registry = FakeRegistry()
    executable = tmp_path / "Pour Notify" / "PourNotify.exe"
    registry.values[VALUE_NAME] = '"C:\\old\\PourNotify.exe"'

    set_startup_enabled(True, executable, registry)
    assert registry.values == {VALUE_NAME: startup_command(executable)}
    assert registry.write_count == 1

    set_startup_enabled(True, executable, registry)
    assert registry.write_count == 1

    set_startup_enabled(False, executable, registry)
    assert registry.values == {}


def test_existing_configuration_defaults_startup_to_disabled():
    legacy = AppConfig.from_dict({"theme": "dark"})
    assert legacy.theme == "dark"
    assert legacy.start_with_windows is False


def test_legacy_startup_entry_is_moved_to_recoverable_backup(tmp_path):
    startup = tmp_path / "Startup"
    backup = tmp_path / "backup"
    startup.mkdir()
    shortcut = startup / "PourNotify.lnk"
    shortcut.write_bytes(b"legacy shortcut")
    (startup / "Unrelated.lnk").write_bytes(b"keep")

    assert legacy_startup_entries(startup) == [shortcut]
    moved = migrate_legacy_startup_entries(startup, backup)

    assert not shortcut.exists()
    assert (startup / "Unrelated.lnk").exists()
    assert moved == [backup / "PourNotify.lnk.before-v1.0.4"]
    assert moved[0].read_bytes() == b"legacy shortcut"
