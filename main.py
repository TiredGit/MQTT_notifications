import uvicorn
from fastapi import FastAPI, Request, Path, HTTPException
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from contextlib import asynccontextmanager
import asyncio
from aiomqtt import Client

import json

import state
from state import add_or_update, remove
import logging

from clickhouse import clickhouse_tables, json_config_to_clickhouse, clickhouse_get, clickhouse_insert_commands
from notifications import listen_for_notifications, get_life

from datetime import datetime

import call

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await clickhouse_tables()
    task_check = asyncio.create_task(listen_for_configs())
    task_life = asyncio.create_task(get_life())
    task_listen_messages = asyncio.create_task(listen_for_notifications())
    yield
    task_check.cancel()
    task_life.cancel()
    task_listen_messages.cancel()


async def listen_for_configs():
    logger.info('Listening for configs')
    while True:
        try:
            async with Client("mqtt") as client:
                await client.subscribe("intercom/+/config")
                logger.info("Connected to MQTT broker")

                async for message in client.messages:
                    try:
                        my_topic = message.topic
                        my_payload = json.loads(message.payload)
                        logger.info(f"New MQTT message: topic={message.topic}, payload={my_payload}")

                        if my_payload != "":

                            mac = str(my_topic).split("/")[1]
                            reconnect = False

                            event = my_payload.get("event")
                            if event == "added" or event == "modified":
                                config = my_payload.get("new_config")
                                logger.info(f"[CONFIG] {config}")
                                new_or_reconnect = await add_or_update(mac, config)
                                if new_or_reconnect == 'new/mod':
                                    logger.info(f"[{event.upper()}] {mac} добавлен/обновлён")
                                else:
                                    logger.info(f"[CONNECT] {mac} подключение восстановлено")
                                    reconnect = True
                            else:
                                old_config = my_payload.get("old_config")
                                await remove(mac, old_config)
                                logger.info(f"[REMOVED] {mac} удалён")
                            await json_config_to_clickhouse(mac, my_payload, reconnect)
                            logger.info(f"json sent")
                    except Exception as e:
                        logger.error(f"Ошибка при обработке MQTT-сообщения: {e}")
        except Exception as e:
            logger.error(f"Ошибка при подписке на MQTT: {e}")


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(call.call_router)


@app.get("/")
async def main(request: Request):
    logger.info(f"{state.door_phones}")
    return templates.TemplateResponse(
        request, "main.html", {"door_phones": state.door_phones}
    )


@app.get("/notifications")
async def main(request: Request):
    selected_mac = request.query_params.get("mac", "all")
    selected_type = request.query_params.get("type", "config")
    selected_time = request.query_params.get("time", "all")
    logger.info(f"selected_mac={selected_mac}, selected_type={selected_type}, selected_time={selected_time}")
    configs = await clickhouse_get('intercom_configs', 'configs',
                                   selected_mac, selected_type, selected_time)
    messages = await clickhouse_get('intercom_messages', 'messages',
                                    selected_mac, selected_type, selected_time)
    life = await clickhouse_get('intercom_life', 'life',
                                selected_mac, selected_type, selected_time)
    management_commands = await clickhouse_get('management_commands', 'commands',
                                               selected_mac, selected_type, selected_time)
    return templates.TemplateResponse(
        request, "notifications.html", {"configs": configs, "messages": messages,
                                        "life": life, "commands": management_commands,
                                        "door_phones": state.door_phones,
                                        "selected_mac": selected_mac, "selected_type": selected_type,
                                        "selected_time": selected_time}
    )


@app.get("/calls")
async def main(request: Request):
    return templates.TemplateResponse(
        request, "calls.html", {"calls": state.current_calls}
    )


@app.get("/doorphones/{mac}")
async def main(request: Request, mac: str = Path(..., min_length=17, max_length=17)):
    return templates.TemplateResponse(
        request, "doorphone.html", {"door_phone": state.door_phones[mac], "mac": mac}
    )


@app.post("/doorphones/{mac}/open-door")
async def open_door(mac: str = Path(..., min_length=17, max_length=17)):
    try:
        time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event = "open-door"
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
    return RedirectResponse(f"/doorphones/{mac}/", status_code=303)


@app.post("/doorphones/{mac}/delete")
async def delete_old_intercom(mac: str = Path(..., min_length=17, max_length=17)):
    time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if mac not in state.door_phones:
        await clickhouse_insert_commands(time, mac, "mac-info-delete", "fail")
        raise HTTPException(status_code=404, detail="Домофон не найден")

    state.full_remove(mac)
    logger.info(f"Данные об {mac} удалены из управляющего сервиса")
    async with Client("mqtt") as client:
        await client.publish(f'intercom/{mac}/config',
                             payload=json.dumps(""), qos=1, retain=True)
        logger.info(f"Обнуление mqtt для {mac}")
    await clickhouse_insert_commands(time, mac, "mac-info-delete", "success")
    return RedirectResponse(f"/", status_code=303)


@app.get('/api/doorphones/data')
async def doorphones_data():
    return state.door_phones



if __name__ == '__main__':
    uvicorn.run("main:app", port=8001, reload=True, host='0.0.0.0')
