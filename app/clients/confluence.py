import json
import ssl
import urllib.request
from html.parser import HTMLParser
from dataclasses import dataclass

from app.config import ConfluenceSettings


class ConfluenceAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseScheduleEntry:
    release_id: str
    release_date: str


class ConfluenceAPIClient:
    def __init__(self, settings: ConfluenceSettings) -> None:
        self.settings = settings
        self._ssl_context = ssl.create_default_context()

    def fetch_release_date(self, release_id: str) -> str:
        self._validate_settings()
        page_id = self.settings.release_schedule_page_id
        url = f"{self.settings.api_base_url}/content/{page_id}?expand=body.storage,version"
        request = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(request, context=self._ssl_context, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))

        html = (((payload.get("body") or {}).get("storage") or {}).get("value") or "")
        release_date = _find_release_date_in_schedule(html, release_id)
        if not release_date:
            raise ConfluenceAPIError(f"Could not find release date for {release_id} in Confluence schedule")
        return release_date

    def list_releases(self) -> list[ReleaseScheduleEntry]:
        self._validate_settings()
        page_id = self.settings.release_schedule_page_id
        url = f"{self.settings.api_base_url}/content/{page_id}?expand=body.storage,version"
        request = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(request, context=self._ssl_context, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))

        html = (((payload.get("body") or {}).get("storage") or {}).get("value") or "")
        return _list_releases_from_schedule(html)

    def _validate_settings(self) -> None:
        if not self.settings.api_base_url:
            raise ConfluenceAPIError("CONFLUENCE_API_BASE_URL is not configured")
        if not self.settings.api_token:
            raise ConfluenceAPIError("CONFLUENCE_API_TOKEN is not configured")
        if not self.settings.release_schedule_page_id:
            raise ConfluenceAPIError("CONFLUENCE_RELEASE_SCHEDULE_PAGE_ID is not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_token}",
            "Accept": "application/json",
        }


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables = []
        self._current_table = []
        self._current_row = []
        self._current_cell = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current_table = []
        elif tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []
        elif tag == "br" and self._in_cell:
            self._current_cell.append("\n")

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            text = "".join(self._current_cell).strip()
            self._current_row.append(" ".join(text.split()))
            self._in_cell = False
        elif tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
        elif tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell.append(data)


def _find_release_date_in_schedule(html: str, release_id: str) -> str:
    for entry in _list_releases_from_schedule(html):
        if entry.release_id == release_id:
            return entry.release_date
    raise ConfluenceAPIError(f"Release {release_id} not found in Confluence schedule table")


def _list_releases_from_schedule(html: str) -> list[ReleaseScheduleEntry]:
    parser = _TableParser()
    parser.feed(html)
    entries: list[ReleaseScheduleEntry] = []
    for table in parser.tables:
        if not table:
            continue
        header = table[0]
        try:
            release_date_index = header.index("Плановая дата релиза")
            release_link_index = header.index("Ссылка на релиз")
        except ValueError:
            continue
        for row in table[1:]:
            if len(row) <= max(release_date_index, release_link_index):
                continue
            release_date = row[release_date_index]
            release_link = row[release_link_index]
            release_id = _extract_release_id(release_link)
            if release_id and release_date:
                entries.append(ReleaseScheduleEntry(release_id=release_id, release_date=release_date))
    return entries


def _extract_release_id(release_link: str) -> str:
    if not release_link:
        return ""
    text = release_link.strip().rstrip("/")
    if "/" in text:
        return text.split("/")[-1]
    return text
