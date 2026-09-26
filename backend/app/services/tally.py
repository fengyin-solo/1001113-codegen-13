"""理货作业业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "tally"
REQUIRED_FIELDS = ["理货单号", "关联航次", "理货方式"]
STATUS_ORDER = ["待理货", "理货中", "待复核", "已完成"]
ACTION_RULES = {"开始理货": "理货中", "提交复核": "待复核", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []


class TallyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("理货单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"理货单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于理货作业可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if target == STATUS_ORDER[-1] and not self._review_passed(entry_id):
            return None, "理货箱量、残损箱数与随附记录的差异尚未复核通过，不能直接结单；请先完成理货差异复核"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"理货单已{action}"

    @staticmethod
    def _review_passed(entry_id: int) -> bool:
        conclusions = [
            row
            for row in store.rows("tally_review")
            if int(row.get("tally_id", 0)) == entry_id
        ]
        return bool(conclusions and conclusions[-1].get("复核结论") == "通过")

    def apply_review_result(self, entry: dict[str, Any], *, passed: bool) -> dict[str, Any]:
        """理货差异复核回写：通过即结单（已完成），对不上则退回理货岗返工。"""
        entry["status"] = STATUS_ORDER[-1] if passed else "理货中"
        entry["pending"] = not passed
        entry["abnormal"] = not passed
        return entry
