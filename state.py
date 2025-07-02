from typing import Optional

door_phones = {}
last_seen = {}


async def add_or_update(mac: str, config: dict):
    if mac in door_phones:
        if (door_phones[mac]["location"] == config["location"] and
                door_phones[mac]["apartments"] == config["apartments"] and
                door_phones[mac]["allowed_keys"] == config["allowed_keys"]):
            door_phones[mac]["active"] = True
            door_phones[mac]["error"] = False
            return 'connect'
    door_phones[mac] = config
    door_phones[mac]["active"] = True
    door_phones[mac]["error"] = False
    return 'new/mod'


async def remove(mac: str, config: Optional[dict] = None, error=False):
    if mac not in door_phones:
        door_phones[mac] = config
    door_phones[mac]["active"] = False
    if error:
        door_phones[mac]["error"] = True


def full_remove(mac: str):
    door_phones.pop(mac, None)
    last_seen.pop(mac, None)


current_calls = {}
