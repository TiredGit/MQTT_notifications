from fastapi import APIRouter, Path
from starlette.responses import RedirectResponse

import state
import logging

import json
from datetime import datetime
from clickhouse import clickhouse_insert_commands
from aiomqtt import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

call_router = APIRouter()


async def call_handler(time, mac, event, apartment, location):
    if mac in state.door_phones:
        if event == "call-start":
            state.current_calls[mac] = {"time": time, "apartment": apartment, "location": location}
            logger.info(f"call start - {state.current_calls}")
        if event == "call-end":
            state.current_calls.pop(mac)
            logger.info(f"call end - {state.current_calls}")
    else:
        logger.warning(f"Данный домофон не подключен к сети {mac}")


@call_router.post("/calls/{mac}/open-door")
async def call_open(mac: str = Path(..., min_length=17, max_length=17)):
    logger.info(f"open door - {mac}")
    try:
        time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event = "call-response"
        status = "success"
        async with Client("mqtt") as client:
            await client.publish(f'intercom/{mac}/management',
                                 payload=json.dumps({"time": time,
                                                     "event": event,
                                                     "status": status}),
                                 qos=1)
            await clickhouse_insert_commands(time, mac, event, status)
            logger.info(f'Отправлен запрос на {mac} - Открыть дверь')
    except Exception as e:
        logger.error(e)
    return RedirectResponse(f"/calls/", status_code=303)


@call_router.get("/calls/data")
async def calls_data():
    return state.current_calls

