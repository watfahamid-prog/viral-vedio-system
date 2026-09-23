import requests
from config import DISCORD_WEBHOOK_URL


def notify(message: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    response = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=15)
    response.raise_for_status()
    return True
