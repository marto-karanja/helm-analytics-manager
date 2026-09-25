import os

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


def build_session(path: str) -> AuthorizedSession | None:
    """None when no key is configured yet, so the collector idles instead of crashing."""
    if not path or not os.path.isfile(path):
        return None
    credentials = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    return AuthorizedSession(credentials)
