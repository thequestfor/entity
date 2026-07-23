import argparse
import asyncio
import getpass
import os
from pathlib import Path

from dotenv import load_dotenv

from agent.connectors.telegram import _secure_session, _telethon_types
from agent.intelligence.config import IntelligenceConfig


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Authorize Telegram locally or list followed public channels."
    )
    parser.add_argument(
        "command", choices=("authorize", "channels"),
        help="Authorize the account or discover eligible public channels."
    )
    args = parser.parse_args(argv)
    load_dotenv()
    config = IntelligenceConfig.from_env()
    if not config.telegram_api_id or not config.telegram_api_hash:
        parser.error(
            "Set ENTITY_TELEGRAM_API_ID and ENTITY_TELEGRAM_API_HASH in .env first."
        )
    asyncio.run(_run(args.command, config))


async def _run(command, config):
    TelegramClient, Channel = _telethon_types()
    session_path = Path(config.telegram_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(session_path), int(config.telegram_api_id), config.telegram_api_hash,
        device_model="Entity read-only intelligence", app_version="0.4"
    )
    try:
        await client.start(
            phone=lambda: input("Telegram phone number (international format): ").strip(),
            password=lambda: getpass.getpass("Telegram two-step password: ")
        )
        if command == "authorize":
            me = await client.get_me()
            identity = getattr(me, "username", None) or getattr(me, "id", "account")
            print(f"Telegram authorization stored locally for {identity}.")
            print("Next run: .venv/bin/python -m agent.intelligence.telegram_auth channels")
            return

        channels = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            username = str(getattr(entity, "username", "") or "")
            if isinstance(entity, Channel) and entity.broadcast and username:
                channels.append((dialog.name or username, username, entity.id))
        channels.sort(key=lambda row: row[0].casefold())
        if not channels:
            print("No followed public broadcast channels were found.")
            return
        print("Eligible followed public channels (private chats/groups excluded):")
        for title, username, channel_id in channels:
            print(f"  @{username:<32} {title} [id={channel_id}]")
        print("\nAfter review, add selected usernames to ENTITY_TELEGRAM_CHANNELS.")
    finally:
        await client.disconnect()
        _secure_session(session_path)
        _secure_directory(session_path.parent)


def _secure_directory(path):
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


if __name__ == "__main__":
    main()
