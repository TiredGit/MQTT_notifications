from unittest.mock import AsyncMock, MagicMock

import pytest

import clickhouse


@pytest.mark.asyncio
@pytest.mark.parametrize("time,mac,event,new_config,old_config", [
    ("2025-07-01 12:00:00", "00:11:22:33:44:55", "added", {"location": "Hall", "apartments": [101]}, None),
    ("2025-07-01 12:00:00", "00:11:22:33:44:55", "removed", None, {"location": "Hall", "apartments": [101]}),
])
async def test_clickhouse_insert_config(mocker, time, mac, event, new_config, old_config):
    mock_client = mocker.AsyncMock()
    mocker.patch("clickhouse.init_client", return_value=mock_client)
    clickhouse.client = mock_client

    await clickhouse.clickhouse_insert_config(time, mac, event, new_config, old_config)

    mock_client.insert.assert_called_once()

    called_table = mock_client.insert.call_args[0][0]
    assert called_table == "intercom_configs"

    data = mock_client.insert.call_args[0][1]
    row = data[0]

    assert row[0] == "config"
    assert row[3] == event

    if new_config:
        assert row[4] == str(new_config)
        assert row[5] is None
    elif old_config:
        assert row[5] == str(old_config)
        assert row[4] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time,mac,event,status,door_status,reason,key,result,apartment,location",
    [
        ("2025-07-01 12:00:00", "00:11:22:33:44:55", "ring", "success", "open", None, 123, "ok", "5", "X1"),
        ("2025-07-01 12:05:00", "00:11:22:33:44:56", "answer", "fail", "closed", "timeout", None, None, None, None),
    ],
)
async def test_clickhouse_insert_message(mocker, time, mac, event, status, door_status, reason, key, result, apartment,
                                         location,):
    mock_client = mocker.AsyncMock()
    mocker.patch("clickhouse.init_client", return_value=mock_client)
    clickhouse.client = mock_client

    await clickhouse.clickhouse_insert_message(
        time, mac, event, status, door_status, reason, key, result, apartment, location
    )

    mock_client.insert.assert_called_once()

    called_table = mock_client.insert.call_args[0][0]
    assert called_table == "intercom_messages"

    data = mock_client.insert.call_args[0][1]
    row = data[0]

    assert row[0] == "message"

    assert row[2] == mac
    assert row[3] == event
    assert row[4] == status
    assert row[8] == result
    assert row[9] == apartment
    assert row[10] == location


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time,mac,status",
    [
        ("2025-07-01 12:00:00", "00:11:22:33:44:55", "success"),
        ("2025-07-01 12:05:00", "00:11:22:33:44:56", "fail"),
    ],
)
async def test_clickhouse_insert_life(mocker, time, mac, status):
    mock_client = mocker.AsyncMock()
    mocker.patch("clickhouse.init_client", return_value=mock_client)
    clickhouse.client = mock_client

    await clickhouse.clickhouse_insert_life(time, mac, status)

    mock_client.insert.assert_called_once()

    called_table = mock_client.insert.call_args[0][0]
    assert called_table == "intercom_life"

    data = mock_client.insert.call_args[0][1]
    row = data[0]

    assert row[0] == "life"

    assert row[2] == mac
    assert row[3] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time,mac,event,status",
    [
        ("2025-07-01 12:00:00", "00:11:22:33:44:55", "open-door", "success"),
        ("2025-07-01 12:05:00", "00:11:22:33:44:56", "call-response", "fail"),
    ],
)
async def test_clickhouse_insert_commands(mocker, time, mac, event, status):
    mock_client = mocker.AsyncMock()
    mocker.patch("clickhouse.init_client", return_value=mock_client)
    clickhouse.client = mock_client

    await clickhouse.clickhouse_insert_commands(time, mac, event, status)

    mock_client.insert.assert_called_once()

    called_table = mock_client.insert.call_args[0][0]
    assert called_table == "management_commands"

    data = mock_client.insert.call_args[0][1]
    row = data[0]

    assert row[0] == "management_commands"

    assert row[2] == mac
    assert row[3] == event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mac, payload, reconnect, expected_event",
    [
        ("00:11:22:33:44:55", {"time": "2025-07-01 12:00:00", "event": "added", "new_config": {"loc": "Hall"}}, False,
         "added"),
        ("00:11:22:33:44:56", {"time": "2025-07-01 12:01:00"}, True, "reconnect"),
        ("00:11:22:33:44:57", {}, False, "unknown"),
    ]
)
async def test_json_config_to_clickhouse(mocker, mac, payload, reconnect, expected_event):
    mock_insert_config = mocker.patch("clickhouse.clickhouse_insert_config", new_callable=AsyncMock)

    await clickhouse.json_config_to_clickhouse(mac, payload, reconnect)

    mock_insert_config.assert_awaited_once()

    called_args = mock_insert_config.call_args[0]
    assert called_args[1] == mac
    assert called_args[0] == payload.get('time', 'unknown')
    assert called_args[2] == expected_event
    assert called_args[3] == payload.get('new_config', None)
    assert called_args[4] == payload.get('old_config', None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table_name, message_name, selected_mac, selected_type, selected_time, expected_conditions",
    [
        ("intercom_messages", "messages", "00:11:22:33:44:55", "message", "1m", [
            "mac = '00:11:22:33:44:55'",
            "notification_type = 'message'",
        ]),
        ("intercom_life", "life", "all", None, "all", []),
        ("management_commands", "commands", None, "management_commands", "10m", [
            "notification_type = 'management_commands'",
        ]),
        ("intercom_configs", "configs", "00:11:22:33:44:56", None, None, [
            "mac = '00:11:22:33:44:56'",
        ]),
    ],
)
async def test_clickhouse_get(mocker, table_name, message_name, selected_mac, selected_type, selected_time, expected_conditions):
    mock_client = AsyncMock()
    mock_result = MagicMock()
    mock_result.named_results.return_value = [{"dummy": "result"}]
    mock_client.query.return_value = mock_result

    mocker.patch("clickhouse.init_client", return_value=mock_client)

    result = await clickhouse.clickhouse_get(table_name, message_name, selected_mac, selected_type, selected_time)

    mock_client.query.assert_awaited_once()
    called_query = mock_client.query.call_args[0][0]

    assert f"FROM {table_name}" in called_query

    for cond in expected_conditions:
        assert cond in called_query

    if selected_time and selected_time != 'all':
        assert "time >=" in called_query or "time >=" in called_query

    assert result == mock_result.named_results()


@pytest.mark.asyncio
async def test_clickhouse_tables(mocker):
    mock_client = AsyncMock()
    mocker.patch("clickhouse.init_client", return_value=mock_client)

    await clickhouse.clickhouse_tables()

    mock_client.command.assert_awaited()

    assert mock_client.command.await_count == 4

    calls = [call.args[0] for call in mock_client.command.await_args_list]
    assert any("CREATE TABLE IF NOT EXISTS intercom_configs" in c for c in calls)
    assert any("CREATE TABLE IF NOT EXISTS intercom_messages" in c for c in calls)
    assert any("CREATE TABLE IF NOT EXISTS intercom_life" in c for c in calls)
    assert any("CREATE TABLE IF NOT EXISTS management_commands" in c for c in calls)
