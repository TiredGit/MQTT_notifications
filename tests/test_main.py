import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from starlette.responses import RedirectResponse

import main

from fastapi.testclient import TestClient
import state


@pytest.mark.asyncio
@pytest.mark.parametrize("config,event,old_config,reconnect", [
    ({"location": "Hall", "apartments": [101]}, "added", None, False),
    ({"location": "Hall", "apartments": [101]}, "added", None, True),
    (None, "deleted", {"location": "Hall2", "apartments": [103]}, False),
])
async def test_listen_for_configs_added_once(mocker, config, event, old_config, reconnect):
    mac = "AA:BB:CC:DD:EE:FF"
    payload = {
        "event": event,
        "new_config": config,
        "old_config": old_config,
    }
    fake_message = MagicMock()
    fake_message.topic = f"intercom/{mac}/config"
    fake_message.payload = json.dumps(payload)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.subscribe = AsyncMock()

    async def single_message():
        yield fake_message
        raise asyncio.CancelledError()

    mock_client.messages.__aiter__.side_effect = single_message
    mocker.patch("main.Client", return_value=mock_client)

    if reconnect:
        reconnect_value = "connect"
        clickhouse_reconnect = True
    else:
        reconnect_value = "new/mod"
        clickhouse_reconnect = False
    mock_add_or_update = mocker.patch("main.add_or_update", new_callable=AsyncMock, return_value=reconnect_value)
    mock_remove = mocker.patch("main.remove", new_callable=AsyncMock)
    mock_clickhouse = mocker.patch("main.json_config_to_clickhouse", new_callable=AsyncMock)

    with pytest.raises(asyncio.CancelledError):
        await main.listen_for_configs()

    mock_client.subscribe.assert_awaited_once_with("intercom/+/config")
    if config:
        mock_add_or_update.assert_awaited_once_with(mac, config)
        mock_remove.assert_not_called()
    if old_config:
        mock_remove.assert_awaited_once_with(mac, old_config)
        mock_add_or_update.assert_not_called()
    mock_clickhouse.assert_awaited_once_with(mac, payload, clickhouse_reconnect)


client = TestClient(main.app)


def test_main_page(mocker):
    mocker.patch.object(state, "door_phones",
                        {"00:11:22:33:44:55": {"location": "X1", "apartments": [1], "allowed_keys": [2]}})
    response = client.get("/")

    assert response.status_code == 200
    assert "00:11:22:33:44:55" in response.text


def test_main_notifications(mocker):
    mocker.patch("main.clickhouse_get", new_callable=AsyncMock, side_effect=[
        [{"config": "c"}], [{"message": "m"}], [{"life": "l"}], [{"command": "cmd"}]
    ])

    mocker.patch.object(state, "door_phones",
                        {"00:11:22:33:44:55": {"location": "X1", "apartments": [1], "allowed_keys": [2]}})

    response = client.get("/notifications?mac=AA:BB:CC:DD:EE:FF&type=config&time=1h")

    assert response.status_code == 200
    html = response.text
    assert "notifications.html" not in html
    assert "00:11:22:33:44:55" in html
    assert "config" in html or "command" in html


def test_main_notifications_empty_data(mocker):
    mocker.patch("main.clickhouse_get", new_callable=AsyncMock, return_value=[])
    mocker.patch.object(state, "door_phones", {})
    response = client.get("/notifications")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_open_door(mocker):
    mac = "11:22:33:44:55:66"

    mock_insert = mocker.patch("main.clickhouse_insert_commands", new_callable=AsyncMock)

    mock_publish = AsyncMock()
    mock_client_instance = MagicMock()
    mock_client_instance.publish = mock_publish
    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client_instance
    mocker.patch("main.Client", return_value=mock_client)

    response = await main.open_door(mac)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == f"/doorphones/{mac}/"

    assert mock_insert.await_count == 1

    mock_publish.assert_awaited_once()
    args, kwargs = mock_publish.call_args
    payload_json = json.loads(kwargs["payload"])
    assert payload_json["event"] == "open-door"
    assert kwargs["qos"] == 1
    assert args[0] == f"intercom/{mac}/management"


@pytest.mark.parametrize("mac,exist", [
    ("00:11:22:33:44:55", True),
    ("00:11:22:33:44:60", False),
])
@pytest.mark.asyncio
async def test_delete_old_intercom(mocker, mac, exist):
    mocker.patch.object(state, "door_phones",
                        {"00:11:22:33:44:55": {"location": "X1", "apartments": [1], "allowed_keys": [2]}})

    mock_insert = mocker.patch("main.clickhouse_insert_commands", new_callable=AsyncMock)

    mock_publish = AsyncMock()
    mock_client_instance = MagicMock()
    mock_client_instance.publish = mock_publish
    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client_instance
    mocker.patch("main.Client", return_value=mock_client)

    mock_full_remove = mocker.patch("state.full_remove")

    if exist:
        response = await main.delete_old_intercom(mac)

        assert isinstance(response, RedirectResponse)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

        mock_full_remove.assert_called_once_with(mac)

        mock_publish.assert_awaited_once()
        args, kwargs = mock_publish.call_args
        assert args[0] == f"intercom/{mac}/config"
        assert kwargs["payload"] == json.dumps("")
        assert kwargs["qos"] == 1
        assert kwargs["retain"] is True

        mock_insert.assert_awaited_once()
        _, _, event, status = mock_insert.call_args.args
        assert event == "mac-info-delete"
        assert status == "success"

    else:
        with pytest.raises(HTTPException) as exc_info:
            await main.delete_old_intercom(mac)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Домофон не найден"

        mock_insert.assert_awaited_once()
        _, _, event, status = mock_insert.call_args.args
        assert event == "mac-info-delete"
        assert status == "fail"


@pytest.mark.asyncio
async def test_doorphones_data(mocker):
    mocker.patch.object(state, "door_phones",
                        {"00:11:22:33:44:55": {"location": "X1", "apartments": [1], "allowed_keys": [2]}})
    response = await main.doorphones_data()
    assert isinstance(response, dict)
    assert response["00:11:22:33:44:55"]["location"] == "X1"
