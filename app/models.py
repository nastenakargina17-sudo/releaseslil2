from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ItemType(str, Enum):
    NEW_FEATURE = "new_feature"
    CHANGE = "change"
    BUGFIX = "bugfix"
    TECHNICAL_IMPROVEMENT = "technical_improvement"
    RELEASE_CANDIDATE = "release_candidate"


class ItemStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    EXCLUDED = "excluded"


class SummaryStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"


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
    category: Optional[ValueCategory]
    status: ItemStatus = ItemStatus.DRAFT
    is_paid_feature: bool = False
    image_paths: List[str] = field(default_factory=list)
    tracker_urls: List[str] = field(default_factory=list)
    grouping_mode: GroupingMode = GroupingMode.SINGLE_TASK


@dataclass
class DigestRelease:
    id: str
    release_date: str
    summary: str
    summary_status: SummaryStatus = SummaryStatus.DRAFT
