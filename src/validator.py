"""向后兼容入口：公共字段校验已迁入 src.contracts。

保留 from src.validator import validate_event 的既有用法。
"""
from src.contracts import validate_event  # noqa: F401  向后兼容的重导出

__all__ = ["validate_event", "REQUIRED"]

# 仅信封必填字段（早期版本口径），供旧调用方引用
REQUIRED = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)
