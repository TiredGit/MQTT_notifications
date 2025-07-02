from unittest.mock import AsyncMock
from fastapi.responses import RedirectResponse
import pytest
import call
import state


@pytest.mark.asyncio
@pytest.mark.parametrize("time,mac,event,apartment,location", [
    ("2025-07-01 12:00:00", "00:11:22:33:44:55", "call-start", "5", "X2"),
    ("2025-07-01 12:00:05", "00:11:22:33:44:55", "call-end", "5", "X2"),
    ("2025-07-01 12:00:10", "00:11:22:33:44:60", "call-start", "4", "X2"),
])
async def test_call_handler(time, mac, event, apartment, location):
    state.door_phones = {"00:11:22:33:44:55": {"location": "X2", "apartments": [1, 3], "allowed_keys": [2, 4],
                                               "active": True, "error": False}}
    if event == "call-end":
        state.current_calls[mac] = {"time": "2025-07-01 12:00:00", "apartment": apartment, "location": location}
    else:
        state.current_calls = {}
    await call.call_handler(time, mac, event, apartment, location)
    if time == "2025-07-01 12:00:00":
        assert state.current_calls[mac]["apartment"] == "5"
        assert state.current_calls[mac]["time"] == "2025-07-01 12:00:00"
    elif time == "2025-07-01 12:00:05":
        assert state.current_calls == {}
    elif time == "2025-07-01 12:00:10":
        assert state.current_calls == {}


@pytest.mark.asyncio
async def test_call_open(mocker):
    mac = "00:11:22:33:44:55"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mocker.patch("call.Client", return_value=mock_client)

    mock_insert = mocker.patch("call.clickhouse_insert_commands", new_callable=AsyncMock)

    response = await call.call_open(mac)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/calls/"

    topic = mock_client.publish.call_args[0][0]
    assert "00:11:22:33:44:55" in topic
    payload = mock_client.publish.call_args[1]["payload"]
    assert "call-response" in payload
    assert mock_insert.call_count == 1


@pytest.mark.asyncio
async def test_calls_data():
    state.current_calls = {"11:11:11:11:11:11": {"time": "2025-07-01 12:00:00", "apartment": "4", "location": "loc"}}
    response = await call.calls_data()
    assert response == state.current_calls
