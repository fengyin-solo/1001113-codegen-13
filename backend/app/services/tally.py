"""理货作业业务规则：状态流转、字段校验与差异复核口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "tally"
REVIEW_MODULE = "tallyreview"
REQUIRED_FIELDS = ["理货单号", "关联航次", "理货方式"]
OPTIONAL_FIELDS = ["理货箱量", "残损箱数", "随附箱量", "理货人员", "完成时间"]
STATUS_ORDER = ["待理货", "理货中", "待复核", "已完成"]
ACTION_RULES = {"开始理货": "理货中", "提交复核": "待复核", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []

# 差异复核口径只有一条：差异 = 理货箱量 - 残损箱数 - 随附箱量。
# 差异为零直接通过；|差异| 超出 ALLOWED_DIFF 才要人工复核；ALLOWED_DIFF 是允许的范围，可按需调整。
ALLOWED_DIFF = 0

CONCLUSION_INCOMPLETE = "资料不全"
CONCLUSION_AUTO_PASS = "零差异通过"
CONCLUSION_TOLERANCE_PASS = "容差通过"
CONCLUSION_PENDING = "待复核"
CONCLUSION_REVIEW_PASS = "复核通过"
CONCLUSION_RETURNED = "复核退回"
PASS_CONCLUSIONS = {CONCLUSION_AUTO_PASS, CONCLUSION_TOLERANCE_PASS, CONCLUSION_REVIEW_PASS}
DECISIONS = {CONCLUSION_REVIEW_PASS, CONCLUSION_RETURNED}
REVIEW_SCOPES = {
    "pending": {CONCLUSION_PENDING},
    "incomplete": {CONCLUSION_INCOMPLETE},
    "passed": PASS_CONCLUSIONS,
    "returned": {CONCLUSION_RETURNED},
}


def _parse_int(value: Any) -> int | None:
    """箱量字段可能是数字、数字字符串或空值；空值与非法值都按缺失处理。"""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _measure(entry: dict[str, Any]) -> dict[str, Any]:
    """按理货单当前数据算差异、挑缺项；随用随算不落库，刷新后自然和理货单一致。"""
    tally_qty = _parse_int(entry.get("理货箱量"))
    damage_qty = _parse_int(entry.get("残损箱数")) or 0
    attached_qty = _parse_int(entry.get("随附箱量"))
    gaps: list[str] = []
    if not str(entry.get("理货人员") or "").strip():
        gaps.append("理货人员缺失")
    if tally_qty is None:
        gaps.append("理货箱量为空")
    if attached_qty is None:
        gaps.append("随附箱量为空")
    diff = None
    if tally_qty is not None and attached_qty is not None:
        diff = tally_qty - damage_qty - attached_qty
    return {"理货箱量": tally_qty, "残损箱数": damage_qty, "随附箱量": attached_qty, "差异": diff, "gaps": gaps}


def _auto_conclusion(measure: dict[str, Any]) -> str:
    """判定口径收成一条：缺项单独挑出，差异为零直接通过，超出允许范围才复核。"""
    if measure["gaps"]:
        return CONCLUSION_INCOMPLETE
    diff = int(measure["差异"])
    if diff == 0:
        return CONCLUSION_AUTO_PASS
    if abs(diff) <= ALLOWED_DIFF:
        return CONCLUSION_TOLERANCE_PASS
    return CONCLUSION_PENDING


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
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS + OPTIONAL_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["理货状态"] = STATUS_ORDER[0]
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
        if action == "确认完成":
            blocker = self._close_blocker(entry)
            if blocker:
                return None, blocker
        if action == "提交复核":
            # 重新提交复核：旧的人工结论作废，新一轮复核从当前数据算起
            self._clear_decision(entry_id)
        entry["status"] = target
        entry["理货状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"理货单已{action}"

    # ---- 理货差异复核 ----

    def review_rows(self, scope: str = "all") -> list[dict[str, Any]]:
        rows = self._review_rows()
        wanted = REVIEW_SCOPES.get(scope)
        if wanted is not None:
            rows = [row for row in rows if row["判定结论"] in wanted]
        return rows

    def review_summary(self) -> dict[str, int]:
        rows = self._review_rows()
        return {
            "待复核": sum(1 for row in rows if row["判定结论"] == CONCLUSION_PENDING),
            "资料不全": sum(1 for row in rows if row["判定结论"] == CONCLUSION_INCOMPLETE),
            "已通过": sum(1 for row in rows if row["判定结论"] in PASS_CONCLUSIONS),
            "已退回": sum(1 for row in rows if row["判定结论"] == CONCLUSION_RETURNED),
        }

    def decide_review(
        self,
        tally_id: int,
        decision: str,
        reason: str,
        reviewer: str,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, tally_id)
        if entry is None:
            return None, f"理货单 {tally_id} 不存在或已归档"
        if decision not in DECISIONS:
            return None, f"复核结论「{decision or '空'}」不在可执行范围（复核通过 / 复核退回）"
        measure = _measure(entry)
        auto = _auto_conclusion(measure)
        if auto == CONCLUSION_INCOMPLETE:
            return None, f"理货单{'、'.join(measure['gaps'])}，先补齐资料再复核"
        if auto != CONCLUSION_PENDING:
            return None, "差异在允许范围内，无需人工复核"
        if decision == CONCLUSION_RETURNED and not reason:
            return None, "复核退回必须说明原因"
        record: dict[str, Any] = {
            "tally_id": tally_id,
            "decision": decision,
            "reason": reason,
            "reviewer": reviewer or "值班复核",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        rows = store.rows(REVIEW_MODULE)
        existing = next((row for row in rows if int(row.get("tally_id", 0)) == tally_id), None)
        if existing is None:
            record["id"] = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            rows.append(record)
        else:
            # 同一张理货单重复复核，只留最新一条结论
            record["id"] = existing["id"]
            existing.update(record)
        if decision == CONCLUSION_RETURNED:
            # 对不上就退回理货员重理：状态退回理货中并标异常
            entry["status"] = "理货中"
            entry["理货状态"] = "理货中"
            entry["pending"] = True
            entry["abnormal"] = True
        return entry, f"理货单已{decision}"

    def _review_rows(self) -> list[dict[str, Any]]:
        decisions = {int(row.get("tally_id", 0)): row for row in store.rows(REVIEW_MODULE)}
        rows: list[dict[str, Any]] = []
        for entry in store.rows(MODULE):
            measure = _measure(entry)
            auto = _auto_conclusion(measure)
            decision = decisions.get(int(entry.get("id", 0)))
            if decision is not None and auto != CONCLUSION_PENDING:
                # 理货单数据已变化，旧结论作废，以理货单当前数据为准
                decision = None
            rows.append({
                "id": entry.get("id"),
                "理货单号": entry.get("理货单号"),
                "关联航次": entry.get("关联航次"),
                "理货状态": entry.get("status"),
                "理货人员": entry.get("理货人员") or "—",
                "理货箱量": measure["理货箱量"],
                "残损箱数": measure["残损箱数"],
                "随附箱量": measure["随附箱量"],
                "差异": measure["差异"],
                "判定结论": decision["decision"] if decision else auto,
                "缺项说明": "、".join(measure["gaps"]),
                "退回原因": str(decision.get("reason") or "") if decision else "",
                "复核人": str(decision.get("reviewer") or "") if decision else "",
                "复核时间": str(decision.get("time") or "") if decision else "",
            })
        return rows

    def _close_blocker(self, entry: dict[str, Any]) -> str | None:
        """结单前过一遍复核口径：箱数对不上就拦下，不能再照样结单。"""
        measure = _measure(entry)
        auto = _auto_conclusion(measure)
        if auto == CONCLUSION_INCOMPLETE:
            return f"差异复核未通过：{'、'.join(measure['gaps'])}，先补齐再结单"
        if auto == CONCLUSION_PENDING:
            decision = self._latest_decision(int(entry.get("id", 0)))
            if decision is None:
                return f"差异 {measure['差异']} 超出允许范围（±{ALLOWED_DIFF}），请先复核再结单"
            if decision["decision"] == CONCLUSION_RETURNED:
                return f"复核已退回（{decision.get('reason') or '未填原因'}），不能结单"
        return None

    @staticmethod
    def _latest_decision(tally_id: int) -> dict[str, Any] | None:
        for row in store.rows(REVIEW_MODULE):
            if int(row.get("tally_id", 0)) == tally_id:
                return row
        return None

    @staticmethod
    def _clear_decision(tally_id: int) -> None:
        rows = store.rows(REVIEW_MODULE)
        rows[:] = [row for row in rows if int(row.get("tally_id", 0)) != tally_id]
