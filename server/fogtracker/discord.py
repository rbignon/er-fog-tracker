"""
Discord webhook integration for player notifications.
"""

import logging

import httpx

from fogtracker.config import get_settings

logger = logging.getLogger(__name__)


async def notify_player_connected(
    twitch_username: str,
    twitch_display_name: str | None,
    twitch_avatar_url: str | None,
    game_id: str,
    game_label: str | None,
) -> None:
    """Send Discord notification when a player connects their mod."""
    settings = get_settings()
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        return

    display_name = twitch_display_name or twitch_username
    base_url = settings.base_url.rstrip("/")
    watch_url = f"{base_url}/watch/{twitch_username}/{game_id}"
    twitch_url = f"https://twitch.tv/{twitch_username}"

    embed = {
        "title": f"{display_name} launched a game",
        "url": watch_url,
        "color": 0x9146FF,  # Twitch purple
        "fields": [
            {"name": "Watch live", "value": watch_url, "inline": False},
            {"name": "Twitch", "value": twitch_url, "inline": True},
        ],
    }
    if twitch_avatar_url:
        embed["thumbnail"] = {"url": twitch_avatar_url}
    if game_label:
        embed["fields"].insert(0, {"name": "Run", "value": game_label, "inline": True})

    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning("Discord webhook rate limited, retry after %s seconds", retry_after)
            elif response.status_code >= 400:
                logger.warning("Discord webhook failed with status %d", response.status_code)
    except Exception as e:
        logger.warning("Discord webhook error: %s", e)
