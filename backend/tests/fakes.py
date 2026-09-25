import requests


class FakeResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class FakeSession:
    """Stands in for AuthorizedSession: records every post and answers from `respond(url, body)`."""

    def __init__(self, respond=None):
        self.respond = respond or (lambda url, body: FakeResponse())
        self.calls: list[dict] = []

    def post(self, url: str, json: dict | None = None, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "kwargs": kwargs})
        return self.respond(url, json)
