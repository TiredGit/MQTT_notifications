from datetime import datetime, timedelta

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import notifications
import state


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,should_call_handler", [
    ("call-start", True),
    ("call-end", True),
    ("open-door", False),
])
async def test_listen_for_notifications(mocker, event_type, should_call_handler):
    mac = "AA:BB:CC:DD:EE:FF"
    payload = {
        "time": "2025-07-01 12:00:00",
        "event": event_type,
        "status": "success",
        "door_status": "open",
        "apartment": 42,
        "location": "Hall"
    }

    fake_message = MagicMock()
    fake_message.topic = f"intercom/{mac}/message"
    fake_message.payload = json.dumps(payload)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.subscribe = AsyncMock()

    async def single_message():
        yield fake_message
        raise asyncio.CancelledError()

    mock_client.messages.__aiter__.side_effect = single_message
    mocker.patch("notifications.Client", return_value=mock_client)

    mock_call_handler = mocker.patch("notifications.call.call_handler", new_callable=AsyncMock)
    mock_ch_insert = mocker.patch("notifications.clickhouse_insert_message", new_callable=AsyncMock)

    with pytest.raises(asyncio.CancelledError):
        await notifications.listen_for_notifications()

    mock_client.subscribe.assert_awaited_once_with("intercom/+/message")
    mock_ch_insert.assert_awaited_once_with(
        payload["time"], mac, payload["event"], payload["status"],
        payload["door_status"], payload.get("reason"), payload.get("key"),
        payload.get("result"), payload.get("apartment"), payload.get("location")
    )

    if should_call_handler:
        mock_call_handler.assert_awaited_once_with(
            payload["time"], mac, event_type,
            payload["apartment"], payload["location"]
        )
    else:
        mock_call_handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, init_last_seen, expect_in_last_seen",
    [
        ("online",  False, True),   # обычное сообщение → должно появиться в last_seen
        ("deleted", True,  False),  # удалённое сообщение → должно удалиться из last_seen
    ]
)
async def test_get_life_parametrized(mocker, status, init_last_seen, expect_in_last_seen):
    mac = "AA:BB:CC:DD:EE:FF"
    time_str = "2025-07-01 12:00:00"

    state.last_seen.clear()
    if init_last_seen:
        state.last_seen[mac] = datetime.now()

    payload = {"time": time_str, "status": status}
    fake_message = MagicMock()
    fake_message.topic = f"intercom/{mac}/life"
    fake_message.payload = json.dumps(payload)

    async def single_message():
        yield fake_message
        raise asyncio.CancelledError()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.messages.__aiter__.side_effect = single_message
    mocker.patch("notifications.Client", return_value=mock_client)

    mock_ch = mocker.patch("notifications.clickhouse_insert_life", new_callable=AsyncMock)

    with pytest.raises(asyncio.CancelledError):
        await notifications.get_life()

    if expect_in_last_seen:
        assert mac in state.last_seen
    else:
        assert mac not in state.last_seen

    mock_ch.assert_awaited_once_with(time_str, mac, status)


@pytest.mark.asyncio
async def test_check_life_status_detects_stale_and_records(mocker):
    mac = "AA:BB:CC:DD:EE:FF"

    state.last_seen.clear()
    state.last_seen[mac] = datetime.now() - timedelta(seconds=20)

    state.door_phones.clear()
    state.door_phones[mac] = {"active": True}

    async def dummy_sleep(seconds):
        dummy_sleep.count += 1
        if dummy_sleep.count > 1:
            raise asyncio.CancelledError()
    dummy_sleep.count = 0
    mocker.patch("notifications.asyncio.sleep", dummy_sleep)

    mock_remove = mocker.patch("notifications.state.remove", new_callable=AsyncMock)
    mock_ch_life = mocker.patch("notifications.clickhouse_insert_life", new_callable=AsyncMock)

    with pytest.raises(asyncio.CancelledError):
        await notifications.check_life_status()

    mock_remove.assert_awaited_once_with(mac, error=True)

    mock_ch_life.assert_awaited_once()
    args = mock_ch_life.call_args.args
    assert args[1] == mac
    assert args[2] == "fail"
