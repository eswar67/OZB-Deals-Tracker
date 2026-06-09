#!/usr/bin/env python3
"""
One-time OAuth2 setup for Gmail + Google Sheets.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a project → enable the Gmail API
  3. Create OAuth2 credentials (Desktop app) → download as credentials.json
  4. Place credentials.json next to this script
  5. Run:  python setup_oauth.py [--force]
  6. A browser window will open — log in and grant permissions
  7. token.json is written; keep it safe (it refreshes automatically)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE       = os.getenv("TOKEN_FILE",       "token.json")


def main():
    creds_path = Path(CREDENTIALS_FILE)
    if not creds_path.exists():
        print(f"\nERROR: {CREDENTIALS_FILE} not found.")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        print("(OAuth 2.0 Client ID → Desktop app → Download JSON)\n")
        return

    token_path = Path(TOKEN_FILE)
    if token_path.exists():
        if "--force" in sys.argv:
            token_path.unlink()
        else:
            print(f"{TOKEN_FILE} already exists. Delete it first if you want to re-authenticate.")
            return

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds: Credentials = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())
    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    print("You can now run: python ozbargain_monitor.py\n")


if __name__ == "__main__":
    main()
