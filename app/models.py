from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ItemType(str, Enum):
    NEW_FEATURE = "new_feature"
    # Legacy transitional value kept until import/review/publication paths migrate to PRODUCT_IMPROVEMENT.
    CHANGE = "change"
    PRODUCT_IMPROVEMENT = "product_improvement"
    CLIENT_CUSTOMIZATION = "client_customization"
    INTERNAL_CHANGE = "internal_change"
    BUGFIX = "bugfix"
    TECHNICAL_IMPROVEMENT = "technical_improvement"
    RELEASE_CANDIDATE = "release_candidate"


class DigestVisibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"


class ItemStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    EXCLUDED = "excluded"


class SummaryStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class PublicationStatus(str, Enum):
    DRAFT = "draft"
    PREVIEW = "preview"
    PUBLISHED = "published"


class ValueCategory(str, Enum):
    TIME_SAVING = "time_saving"
    ERROR_REDUCTION = "error_reduction"
    CLARITY_TRANSPARENCY = "clarity_transparency"
    DAILY_WORK_CONVENIENCE = "daily_work_convenience"
    BETTER_CONTROL = "better_control"
    LESS_COMMUNICATION_OVERHEAD = "less_communication_overhead"


class GroupingMode(str, Enum):
    SINGLE_TASK = "single_task"
    EPIC_GROUP = "epic_group"


@dataclass
class SourceItem:
    id: str
    url: str
    title: str
    description: str
    module: str
    type: ItemType
    digest_visibility: DigestVisibility = DigestVisibility.INTERNAL
    parent_epic_id: Optional[str] = None
    parent_epic_title: Optional[str] = None


@dataclass
class DigestItem:
    id: str
    release_id: str
    source_item_ids: List[str]
    title: str
    description: str
    module: str
    type: ItemType
    digest_visibility: DigestVisibility = DigestVisibility.INTERNAL
    category: Optional[ValueCategory] = None
    status: ItemStatus = ItemStatus.DRAFT
    is_paid_feature: bool = False
    image_paths: List[str] = field(default_factory=list)
    tracker_urls: List[str] = field(default_factory=list)
    grouping_mode: GroupingMode = GroupingMode.SINGLE_TASK
    source_item_titles: List[str] = field(default_factory=list)
    source_item_descriptions: List[str] = field(default_factory=list)
    source_item_modules: List[str] = field(default_factory=list)
    version: int = 1
    updated_at: str = ""


@dataclass
class DigestRelease:
    id: str
    release_date: str
    summary: str
    summary_status: SummaryStatus = SummaryStatus.DRAFT
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    publication_status_note: str = ""
    preview_prepared_by: str = ""
    preview_prepared_at: str = ""
    published_by: str = ""
    published_at: str = ""
    version: int = 1
    updated_at: str = ""


@dataclass
class PublishedDigest:
    release_id: str
    release_date: str
    summary: str
    content: dict
    published_by: str
    published_at: str
