from __future__ import annotations

from enum import StrEnum


class TaskMode(StrEnum):
    FIXED_TOPIC = "fixed_topic"
    DATA_DRIVEN_ARTICLE = "data_driven_article"
    WEEKLY_PLAN = "weekly_plan"


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    DATA_SYNCED = "DATA_SYNCED"
    PLANNED = "PLANNED"
    RESEARCHED = "RESEARCHED"
    WRITTEN = "WRITTEN"
    ASSETS_READY = "ASSETS_READY"
    REVIEWED = "REVIEWED"
    FORMATTED = "FORMATTED"
    WECHAT_DRAFTED = "WECHAT_DRAFTED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED = "FAILED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    PUBLISHED = "PUBLISHED"
    POST_ANALYZED = "POST_ANALYZED"

    def can_transition_to(self, target: TaskStatus) -> bool:
        allowed: dict[TaskStatus, set[TaskStatus]] = {
            self.CREATED: {self.DATA_SYNCED, self.PLANNED, self.FAILED},
            self.DATA_SYNCED: {self.PLANNED, self.FAILED},
            self.PLANNED: {self.RESEARCHED, self.FAILED, self.NEEDS_HUMAN},
            self.RESEARCHED: {self.WRITTEN, self.FAILED, self.NEEDS_HUMAN},
            self.WRITTEN: {self.ASSETS_READY, self.REVIEWED, self.NEEDS_HUMAN, self.FAILED},
            self.ASSETS_READY: {self.REVIEWED, self.FORMATTED, self.FAILED},
            self.REVIEWED: {
                self.ASSETS_READY,
                self.FORMATTED,
                self.WRITTEN,
                self.NEEDS_HUMAN,
                self.FAILED,
            },
            self.FORMATTED: {self.WECHAT_DRAFTED, self.HUMAN_REVIEWED, self.FAILED},
            self.WECHAT_DRAFTED: {self.HUMAN_REVIEWED, self.FAILED},
            self.NEEDS_HUMAN: {self.HUMAN_REVIEWED, self.FAILED},
            self.HUMAN_REVIEWED: {self.PUBLISHED, self.FORMATTED, self.WECHAT_DRAFTED},
            self.PUBLISHED: {self.POST_ANALYZED},
            self.FAILED: {self.CREATED, self.DATA_SYNCED, self.PLANNED},
            self.POST_ANALYZED: set(),
        }
        return target in allowed[self]


TASK_RUN_IN_FLIGHT_STATUSES = frozenset(
    {
        TaskStatus.DATA_SYNCED,
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
    }
)


class ProbeStatus(StrEnum):
    AVAILABLE = "available"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    NO_DATA = "no_data"
    NOT_RUN = "not_run"
    ERROR = "error"


class EvidenceType(StrEnum):
    REAL = "real"
    MOCK = "mock"
    LOCAL = "local"
