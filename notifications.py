import asyncio
from aiomqtt import Client
import json
import logging

from clickhouse import clickhouse_insert_message, clickhouse_insert_life
from datetime import datetime

import call

import state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def listen_for_notifications():
    while True:
        try:
            async with Client("mqtt") as client:
                await client.subscribe("intercom/+/message")

                async for message in client.messages:
                    try:
                        my_topic = message.topic
                        my_payload = json.loads(message.payload)
                        logger.info(f"New MQTT message: topic={message.topic}, payload={my_payload}")
                        mac = str(my_topic).split("/")[1]

                        time = my_payload.get("time")
                        event = my_payload.get("event")
                        status = my_payload.get("status")
                        door_status = my_payload.get("door_status")
                        reason = my_payload.get("reason", None)
                        key = my_payload.get("key", None)
                        result = my_payload.get("result", None)

                        apartment = my_payload.get("apartment", None)
                        location = my_payload.get("location", None)

                        if event == "call-start" or event == "call-end":
                            await call.call_handler(time, mac, event, apartment, location)

                        await clickhouse_insert_message(time, mac, event, status, door_status, reason, key, result,
                                                        apartment, location)

                    except Exception as e:
                        logger.error(f"Ошибка при обработке MQTT-сообщения: {e}")
        except Exception as e:
            logger.error(f"Ошибка при подписке на MQTT: {e}")


async def check_life_status():
    while True:
        await asyncio.sleep(12)

        now = datetime.now()
        for last_mac, last_time in list(state.last_seen.items()):
            delta = (now - last_time).total_seconds()
            if delta > 12:
                logger.warning(f"[FAIL] Life-сообщение от {last_mac} не приходило {delta} сек.")
                if state.door_phones[last_mac]["active"]:
                    await state.remove(last_mac, error=True)
                    logger.info(f"mac {last_mac} отключен из-за ошибки")
                await clickhouse_insert_life(now.strftime("%Y-%m-%d %H:%M:%S"), last_mac, "fail")


async def get_life():

    check_life_task = asyncio.create_task(check_life_status())

    while True:
        try:
            async with Client("mqtt") as client:
                await client.subscribe("intercom/+/life")

                async for message in client.messages:
                    try:
                        my_topic = message.topic
                        my_payload = json.loads(message.payload)
                        logger.info(f"New MQTT message: topic={message.topic}, payload={my_payload}")
                        mac = str(my_topic).split("/")[1]
                        time = my_payload.get("time")
                        status = my_payload.get("status")
                        if status != 'deleted':
                            state.last_seen[mac] = datetime.now()
                            logger.info(f"последнее сообщение {mac} - {state.last_seen[mac]}")
                        else:
                            if mac in state.last_seen:
                                logger.info(f"{mac} был отключен")
                                state.last_seen.pop(mac, None)

                        await clickhouse_insert_life(time, mac, status)

                    except Exception as e:
                        logger.error(f"Ошибка при обработке MQTT-сообщения: {e}")
        except asyncio.CancelledError:
            logger.info("get_life task cancelled, cancelling internal task")
            check_life_task.cancel()
            await check_life_task
            raise
        except Exception as e:
            logger.error(f"Ошибка при подписке на MQTT: {e}")
