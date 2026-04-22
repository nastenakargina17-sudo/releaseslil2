import json
import ssl
import urllib.request
from typing import Any, Dict, List, Optional

from app.config import TrackerSettings
from app.models import ItemType, SourceItem
from app.review_utils import normalize_tracker_issue_url


class TrackerAPIError(RuntimeError):
    pass


MODULE_NAME_MAP = {
    "Sourcing": "Работные сайты",
    "Communication": "Коммуникации",
    "ATSCore": "Ядро",
    "AtsCore": "Ядро",
    "AtsFramework": "Ядро",
    "Client Task": "Клиентский запрос",
    "Configurator": "Конфигуратор",
    "Assessment": "Тестирование и оценка",
    "Reporting": "Отчеты и импорты",
    "Task Tracker": "Трекер задач и отложенные действия",
    "Auth": "Авторизация и ролевая модель",
    "OpenAPI": "API и Webhook",
    "Telephony": "Телефония",
    "Persons": "Физические лица",
    "Geocoding": "Геокодирование",
    "Security Profiles": "Профиль видимости",
    "Audit": "Аудит",
    "Personal Data": "Персональные данные",
    "AI": "Искусственный интеллект",
    "MS Sourcing Integrator": "Микросервисы",
    "MS Activity Stream": "Микросервисы",
    "MS Landings": "Микросервисы",
    "MS Magnit": "Микросервисы",
    "MS Marketplace": "Микросервисы",
    "MS Megafon": "Микросервисы",
    "MS Mindight SDE": "Микросервисы",
    "MS VTB": "Микросервисы",
    "MS X5": "Микросервисы",
}


class TrackerAPIClient:
    def __init__(self, settings: TrackerSettings) -> None:
        self.settings = settings
        self._parent_cache: Dict[str, dict[str, Any]] = {}
        self._ssl_context = ssl.create_default_context()

    def fetch_release_items(self, release_id: str) -> List[SourceItem]:
        self._validate_settings()
        links = self._fetch_release_links(release_id)
        linked_keys = [item["object"]["key"] for item in links if item.get("object", {}).get("key")]
        source_items: List[SourceItem] = []
        for key in linked_keys:
            issue = self._fetch_issue(key)
            source_item = self._map_source_item(issue)
            if source_item is not None:
                source_items.append(source_item)
        return source_items

    def _fetch_release_links(self, release_id: str) -> List[dict[str, Any]]:
        url = f"{self.settings.api_base_url}/issues/{release_id}/links"
        payload = self._get_json(url)
        if not isinstance(payload, list):
            raise TrackerAPIError("Tracker release links response must be a list")
        return payload

    def _fetch_issue(self, key: str) -> dict[str, Any]:
        url = f"{self.settings.api_base_url}/issues/{key}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            raise TrackerAPIError(f"Tracker issue payload for {key} must be an object")
        return payload

    def _map_source_item(self, item: Any) -> Optional[SourceItem]:
        if not isinstance(item, dict):
            raise TrackerAPIError("Tracker item must be an object")

        issue_key = str(item.get("key") or item.get("id") or "")
        item_id = issue_key
        url = normalize_tracker_issue_url(issue_key, str(item.get("url") or item.get("self") or ""))
        if not item_id or not url:
            raise TrackerAPIError("Tracker item must include id/key and url/self")

        raw_type = ((item.get("type") or {}).get("key") or "").strip()
        if raw_type == "epic":
            return None

        item_type = _classify_item_type(item)
        if item_type is None:
            return None
        parent_epic_id = None
        parent_epic_title = None
        parent = item.get("parent")
        if isinstance(parent, dict) and parent.get("key"):
            parent_payload = self._fetch_parent_issue(str(parent["key"]))
            if ((parent_payload.get("type") or {}).get("key") or "").strip() == "epic":
                parent_epic_id = str(parent_payload.get("key"))
                parent_epic_title = str(parent_payload.get("summary") or parent_epic_id)

        return SourceItem(
            id=item_id,
            url=url,
            title=str(item.get("summary") or ""),
            description=str(item.get("description") or ""),
            module=_map_module_name(item.get("components") or []),
            type=item_type,
            parent_epic_id=parent_epic_id,
            parent_epic_title=parent_epic_title,
        )

    def _fetch_parent_issue(self, key: str) -> dict[str, Any]:
        if key not in self._parent_cache:
            self._parent_cache[key] = self._fetch_issue(key)
        return self._parent_cache[key]

    def _validate_settings(self) -> None:
        if not self.settings.api_base_url:
            raise TrackerAPIError("TRACKER_API_BASE_URL is not configured")
        if not self.settings.api_token:
            raise TrackerAPIError("TRACKER_API_TOKEN is not configured")
        if not self.settings.org_id:
            raise TrackerAPIError("TRACKER_ORG_ID is not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"OAuth {self.settings.api_token}",
            "X-Org-Id": self.settings.org_id,
            "Accept": "application/json",
        }

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(request, context=self._ssl_context, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


def _classify_item_type(item: dict[str, Any]) -> Optional[ItemType]:
    raw_type = ((item.get("type") or {}).get("key") or "").strip()
    tags = item.get("tags") or []
    tags_set = {str(tag) for tag in tags}
    in_release = str(item.get("inTheReleaseDescription") or "").strip()
    project_primary = (((item.get("project") or {}).get("primary") or {}).get("display") or "").strip()

    if raw_type == "osibkaS":
        return ItemType.BUGFIX

    if raw_type == "story":
        if "Tech🔧" in tags_set:
            return ItemType.TECHNICAL_IMPROVEMENT
        if "Product Development" in project_primary and in_release == "Клиентский и внутренний":
            return ItemType.NEW_FEATURE
        if in_release == "Только внутренний":
            return ItemType.CHANGE
        if in_release == "Нет":
            return ItemType.RELEASE_CANDIDATE

    return None


def _map_module_name(components: List[Any]) -> str:
    displays = []
    for component in components:
        if isinstance(component, dict) and component.get("display"):
            displays.append(str(component["display"]))
    for display in displays:
        if display in MODULE_NAME_MAP:
            return MODULE_NAME_MAP[display]
    if displays:
        return displays[0]
    return "Клиентский запрос"
