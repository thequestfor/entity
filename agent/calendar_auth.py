from agent.calendar import GoogleCalendarClient


def main():
    from dotenv import load_dotenv

    load_dotenv()

    client = GoogleCalendarClient()

    if not client.enabled:
        print("Google Calendar is disabled. Set ENTITY_GOOGLE_CALENDAR_ENABLED=true.")
        return

    if not client.credentials_path.exists():
        print(
            "Google Calendar credentials are missing: "
            f"{client.credentials_path}"
        )
        return

    client._service()
    print(f"Google Calendar authorized. Token saved to {client.token_path}.")


if __name__ == "__main__":
    main()
