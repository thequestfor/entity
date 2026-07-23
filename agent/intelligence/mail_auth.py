import argparse

from dotenv import load_dotenv

from agent.connectors.gmail import GmailConnector
from agent.connectors.outlook import OutlookConnector
from agent.intelligence.config import IntelligenceConfig


def main():
    parser = argparse.ArgumentParser(
        description="Authorize Entity's read-only mail connectors."
    )
    parser.add_argument(
        "provider",
        choices=("gmail", "outlook", "both"),
        help="mail provider to authorize"
    )
    args = parser.parse_args()
    load_dotenv()
    config = IntelligenceConfig.from_env()

    if args.provider in {"gmail", "both"}:
        print("Opening Google consent for read-only Gmail access...")
        path = GmailConnector.authorize(
            config.gmail_credentials_path,
            config.gmail_token_path
        )
        print(f"Gmail authorized. Private token saved to {path}.")

    if args.provider in {"outlook", "both"}:
        if not config.outlook_client_id:
            raise SystemExit(
                "ENTITY_OUTLOOK_CLIENT_ID is required before Outlook authorization."
            )
        print("Opening Microsoft consent for delegated read-only mail access...")
        path = OutlookConnector.authorize(
            config.outlook_client_id,
            config.outlook_tenant,
            config.outlook_token_cache_path
        )
        print(f"Outlook authorized. Private token cache saved to {path}.")


if __name__ == "__main__":
    main()
