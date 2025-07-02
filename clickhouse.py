from clickhouse_connect import get_async_client
import logging

from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = None


async def init_client():
    global client
    if client is None:
        client = await get_async_client(host='clickhouse', port=8123, username='default', password='12345')
    return client


async def clickhouse_tables():
    global client
    client = await init_client()
    logger.info("Connected to Clickhouse")

    await client.command('''
    CREATE TABLE IF NOT EXISTS intercom_configs (
        notification_type String,
        time DateTime,
        mac String,
        event String,
        new_config Nullable(String),
        old_config Nullable(String)
    ) ENGINE = MergeTree() 
    ORDER BY time
    ''')
    logger.info("Table intercom_configs created")

    await client.command('''
    CREATE TABLE IF NOT EXISTS intercom_messages (
        notification_type String,
        time DateTime,
        mac String,
        event String,
        status String,
        door_status String,
        reason Nullable(String),
        key Nullable(String),
        result Nullable(String),
        apartment Nullable(String),
        location Nullable(String)
    ) ENGINE = MergeTree() 
    ORDER BY time
    ''')
    logger.info("Table intercom_messages created")

    await client.command('''
    CREATE TABLE IF NOT EXISTS intercom_life (
        notification_type String,
        time DateTime,
        mac String,
        status String
    ) ENGINE = MergeTree() 
    ORDER BY time
    ''')
    logger.info("Table intercom_life created")

    await client.command('''
        CREATE TABLE IF NOT EXISTS management_commands (
            notification_type String,
            time DateTime,
            mac String,
            event String,
            status String
        ) ENGINE = MergeTree() 
        ORDER BY time
        ''')
    logger.info("Table management_commands created")


async def clickhouse_insert_config(time: str, mac: str, event: str, new_config: dict | None, old_config: dict | None):
    logger.info("Inserting new config")
    global client
    client = await init_client()

    if new_config:
        new_config_str = str(new_config)
    else:
        new_config_str = None

    if old_config:
        old_config_str = str(old_config)
    else:
        old_config_str = None

    notification_type = 'config'
    time_datetype = datetime.strptime(time, "%Y-%m-%d %H:%M:%S")

    await client.insert('intercom_configs', [[
        notification_type,
        time_datetype,
        mac,
        event,
        new_config_str,
        old_config_str
    ]])
    logger.info("Inserted new config")


async def clickhouse_insert_message(time: str, mac: str, event: str, status: str, door_status: str,
                                    reason: str | None, key: int | None, result: str | None, apartment: str | None,
                                    location: str | None):

    logger.info("Inserting new message")
    global client
    client = await init_client()

    notification_type = 'message'
    time_datetype = datetime.strptime(time, "%Y-%m-%d %H:%M:%S")
    str_key = str(key)

    await client.insert('intercom_messages', [[
        notification_type,
        time_datetype,
        mac,
        event,
        status,
        door_status,
        reason,
        str_key,
        result,
        apartment,
        location
    ]])
    logger.info("Inserted new message")


async def clickhouse_insert_life(time: str, mac: str, status: str):

    logger.info("Inserting new life-message")
    global client
    client = await init_client()

    notification_type = 'life'
    time_datetype = datetime.strptime(time, "%Y-%m-%d %H:%M:%S")

    await client.insert('intercom_life', [[
        notification_type,
        time_datetype,
        mac,
        status
    ]])
    logger.info("Inserted new life-message")


async def clickhouse_insert_commands(time: str, mac: str, event: str, status: str):

    logger.info("Inserting new management commands")
    global client
    client = await init_client()

    notification_type = 'management_commands'
    time_datetype = datetime.strptime(time, "%Y-%m-%d %H:%M:%S")

    await client.insert('management_commands', [[
        notification_type,
        time_datetype,
        mac,
        event,
        status
    ]])
    logger.info("Inserted new management commands")


async def json_config_to_clickhouse(mac, payload, reconnect):
    my_time = payload.get('time', 'unknown')
    if reconnect:
        event = 'reconnect'
    else:
        event = payload.get('event', 'unknown')
    new_config = payload.get('new_config', None)
    old_config = payload.get('old_config', None)
    await clickhouse_insert_config(my_time, mac, event, new_config, old_config)


async def clickhouse_get(table_name, message_name, selected_mac, selected_type, selected_time):
    logger.info(f"Getting {message_name} with {selected_mac}, {selected_type}, {selected_time}")
    global client
    client = await init_client()

    conditions = []

    if selected_mac and selected_mac != 'all':
        conditions.append(f"mac = '{selected_mac}'")

    if selected_type:
        conditions.append(f"notification_type = '{selected_type}'")

    if selected_time and selected_time != 'all':
        now = datetime.now()
        if selected_time == '1m':
            time_from = now - timedelta(minutes=1)
        elif selected_time == '10m':
            time_from = now - timedelta(minutes=10)
        elif selected_time == '1h':
            time_from = now - timedelta(hours=1)
        elif selected_time == '24h':
            time_from = now - timedelta(hours=24)
        else:
            time_from = None

        if time_from:
            conditions.append(f"time >= '{time_from.strftime('%Y-%m-%d %H:%M:%S')}'")

    sql_conditions = f"WHERE {' AND '.join(conditions)}" if conditions else ""


    query = f'''
            SELECT *
            FROM {table_name}
            {sql_conditions}
            ORDER BY time DESC
        '''
    logger.info(f"query: {query}")

    result = await client.query(query)
    logger.info(f"Got {message_name}")

    return result.named_results()
