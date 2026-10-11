"""Small explicit transport double; independent of aiohttp private constructors."""

import json
from unittest.mock import patch


class Response:
    def __init__(self, body, status):
        self.body, self.status = body, status
        self.offset = 0
        self.content = self

    async def read(self, size):
        data = self.body[self.offset : self.offset + size]
        self.offset += len(data)
        return data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class HttpMock:
    def __init__(self):
        self.responses = {}
        self.calls = []

    def __enter__(self):
        self.patcher = patch("aiohttp.ClientSession.request", side_effect=self.request)
        self.patcher.start()
        return self

    def __exit__(self, *args):
        self.patcher.stop()

    def register(self, method, url, *, payload=None, body=None, status=200):
        body = json.dumps(payload) if body is None else body
        self.responses.setdefault((method, url), []).append(Response(body.encode(), status))

    def get(self, url, **kwargs):
        self.register("GET", url, **kwargs)

    def post(self, url, **kwargs):
        self.register("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        self.calls.append((method, str(url), kwargs))
        return self.responses[(method, str(url))].pop(0)
