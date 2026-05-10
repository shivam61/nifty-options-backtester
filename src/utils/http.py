from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logging_utils import get_logger


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class HttpClient:
    min_interval_seconds: float = 0.5
    timeout_seconds: float = 30.0
    session: Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        retry = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request_ts = 0.0
        self.logger = get_logger(self.__class__.__name__)

    def _sleep_if_needed(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.min_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self._sleep_if_needed()
        kwargs.setdefault("timeout", self.timeout_seconds)
        response = self.session.request(method, url, **kwargs)
        self._last_request_ts = time.monotonic()
        response.raise_for_status()
        return response

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)
