import pytest
import state


@pytest.mark.parametrize("mac,config", [
    ("00:11:22:33:44:55", {"location": "X1", "apartments": [1], "allowed_keys": [2]}),
    ("00:11:22:33:44:60", {"location": "X2", "apartments": [1, 3], "allowed_keys": [2, 4]}),
])
@pytest.mark.asyncio
async def test_add_or_update(mac, config):
    state.door_phones = {"00:11:22:33:44:60":
                             {"location": "X2", "apartments": [1, 3], "allowed_keys": [2, 4]}}
    response = await state.add_or_update(mac, config)
    if mac == "00:11:22:33:44:55":
        assert response == "new/mod"
        assert state.door_phones[mac]["active"] is True
        assert state.door_phones[mac]["error"] is False
    else:
        assert response == "connect"


@pytest.mark.parametrize("mac,config,error", [
    ("00:11:22:33:44:55", None, True),
    ("00:11:22:33:44:60", {"location": "X2", "apartments": [1, 3], "allowed_keys": [2, 4], "active": True,
                           "error": False}, False),
])
@pytest.mark.asyncio
async def test_remove(mac, config, error):
    state.door_phones = {"00:11:22:33:44:55": {"location": "X2",
                                               "apartments": [1, 3], "allowed_keys": [2, 4], "active": True,
                                               "error": False}}
    await state.remove(mac, config=config, error=error)
    if mac == "00:11:22:33:44:55":
        assert state.door_phones[mac]["active"] is False
        assert state.door_phones[mac]["error"] is True
    else:
        assert state.door_phones[mac]["active"] is False
        assert state.door_phones[mac]["error"] is False


def test_full_remove():
    mac = "00:11:22:33:44:55"
    state.door_phones = {"00:11:22:33:44:55": {"location": "X2",
                                               "apartments": [1, 3], "allowed_keys": [2, 4], "active": True,
                                               "error": False}}
    state.last_seen = {"00:11:22:33:44:55": "2025-07-01 16:45:20"}
    state.full_remove(mac)

    assert state.door_phones == {}
    assert state.last_seen == {}
