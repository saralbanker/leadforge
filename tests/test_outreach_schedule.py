import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.repositories.settings import SQLiteSettingsRepository  # noqa: E402
from leadforge.server import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_module_env():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", temp_db_path)
    initialize_database()
    yield
    mp.undo()
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


@pytest.fixture
def mock_systemd_env(tmp_path, monkeypatch):
    """Isolates timer file writes to a tmp path and intercepts subprocess.run."""
    fake_timer_file = tmp_path / "systemd" / "user" / "leadforge-daily.timer"
    monkeypatch.setenv("LEADFORGE_SYSTEMD_TIMER_PATH", str(fake_timer_file))

    systemd_state = {
        "active": True,
        "time": "08:00",
        "calls": [],
    }

    def fake_subprocess_run(cmd, *args, **kwargs):
        systemd_state["calls"].append(list(cmd))
        if cmd[:3] == ["systemctl", "--user", "show"]:
            output = (
                f"ActiveState={'active' if systemd_state['active'] else 'inactive'}\n"
                f"SubState={'waiting' if systemd_state['active'] else 'dead'}\n"
                f"UnitFileState=enabled\n"
                f"NextElapseUSecRealtime={'Sat 2026-08-22 ' + systemd_state['time'] + ':00 IST' if systemd_state['active'] else ''}\n"
                f"TimersCalendar={{ OnCalendar=*-*-* {systemd_state['time']}:00 }}\n"
            )
            return MagicMock(returncode=0, stdout=output, stderr="")
        elif cmd[:3] == ["systemctl", "--user", "daemon-reload"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        elif cmd[:3] == ["systemctl", "--user", "enable"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        elif cmd[:3] == ["systemctl", "--user", "restart"]:
            systemd_state["active"] = True
            return MagicMock(returncode=0, stdout="", stderr="")
        elif cmd[:3] == ["systemctl", "--user", "stop"]:
            systemd_state["active"] = False
            return MagicMock(returncode=0, stdout="", stderr="")
        elif cmd[:3] == ["systemctl", "--user", "disable"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run:
        yield {
            "fake_timer_file": fake_timer_file,
            "mock_run": mock_run,
            "systemd_state": systemd_state,
        }


def test_get_schedule_defaults(mock_systemd_env):
    """GET /api/outreach/schedule returns defaults from settings and systemd status."""
    repo = SQLiteSettingsRepository()
    repo.set("outreach.schedule_time", "08:00")
    repo.set("outreach.schedule_enabled", "true")

    res = client.get("/api/outreach/schedule")
    assert res.status_code == 200
    data = res.json()
    assert data["time"] == "08:00"
    assert data["enabled"] is True
    assert data["timer_active"] is True
    assert data["systemd_available"] is True
    assert "08:00" in (data["next_run"] or "")


def test_post_schedule_valid_time(mock_systemd_env):
    """POST /api/outreach/schedule saves valid time, updates timer unit and systemd."""
    env = mock_systemd_env
    env["systemd_state"]["time"] = "09:30"

    res = client.post("/api/outreach/schedule", json={"time": "09:30", "enabled": True})
    assert res.status_code == 200
    data = res.json()
    assert data["time"] == "09:30"
    assert data["enabled"] is True
    assert data["timer_applied"] is True

    # Check settings table
    repo = SQLiteSettingsRepository()
    assert repo.get("outreach.schedule_time") == "09:30"
    assert repo.get("outreach.schedule_enabled") == "true"

    # Check unit file contents
    timer_path = env["fake_timer_file"]
    assert timer_path.exists()
    content = timer_path.read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 09:30:00" in content
    assert "Persistent=true" in content
    assert "RandomizedDelaySec=180" in content

    # Check systemctl commands were called
    calls = env["systemd_state"]["calls"]
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "restart", "leadforge-daily.timer"] in calls

    # GET round-trip
    get_res = client.get("/api/outreach/schedule")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["time"] == "09:30"
    assert get_data["enabled"] is True


@pytest.mark.parametrize(
    "invalid_time",
    [
        "25:00",
        "8:00",
        "ab:cd",
        "08:60",
        "08:00\nExecStart=/bin/rm -rf /",
        "",
        "24:00",
        "-01:00",
        "12:00:00",
        "08:00; rm -rf /",
        "24:01",
        "12:61",
    ],
)
def test_post_schedule_invalid_times(invalid_time, mock_systemd_env):
    """POST /api/outreach/schedule strictly rejects invalid/injection time strings with 422."""
    env = mock_systemd_env
    env["systemd_state"]["calls"].clear()

    res = client.post("/api/outreach/schedule", json={"time": invalid_time, "enabled": True})
    assert res.status_code == 422

    # Verify no systemctl daemon-reload or restart was triggered for this invalid request
    calls = env["systemd_state"]["calls"]
    assert not any("daemon-reload" in c for c in calls)
    assert not any("restart" in c for c in calls)


def test_post_schedule_disabled_stops_timer(mock_systemd_env):
    """POST /api/outreach/schedule with enabled=False persists setting and stops timer."""
    env = mock_systemd_env
    res = client.post("/api/outreach/schedule", json={"time": "08:00", "enabled": False})
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is False

    repo = SQLiteSettingsRepository()
    assert repo.get("outreach.schedule_enabled") == "false"

    calls = env["systemd_state"]["calls"]
    assert ["systemctl", "--user", "stop", "leadforge-daily.timer"] in calls

    # GET round-trip
    get_res = client.get("/api/outreach/schedule")
    assert get_res.status_code == 200
    assert get_res.json()["enabled"] is False


def test_schedule_systemd_unavailable(tmp_path, monkeypatch):
    """When systemctl fails, schedule settings are still saved and response flags systemd as unavailable."""
    fake_timer_file = tmp_path / "systemd" / "user" / "leadforge-daily.timer"
    monkeypatch.setenv("LEADFORGE_SYSTEMD_TIMER_PATH", str(fake_timer_file))

    with patch("subprocess.run", side_effect=FileNotFoundError("systemctl not found")):
        res = client.post("/api/outreach/schedule", json={"time": "14:45", "enabled": True})
        assert res.status_code == 200
        data = res.json()
        assert data["time"] == "14:45"
        assert data["enabled"] is True
        assert data["systemd_available"] is False
        assert data["timer_applied"] is False

        # Setting was saved in DB
        repo = SQLiteSettingsRepository()
        assert repo.get("outreach.schedule_time") == "14:45"

        # GET reports systemd unavailable
        get_res = client.get("/api/outreach/schedule")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["time"] == "14:45"
        assert get_data["systemd_available"] is False
        assert get_data["timer_state"] == "unavailable"
