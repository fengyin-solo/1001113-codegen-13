"""理货差异复核业务规则。

判定口径收成一条：理货单的理货箱量、残损箱数分别与随附记录比对，箱量差异不超过
BOX_TOLERANCE 箱、残损箱数差异不超过 DAMAGE_TOLERANCE 箱即算对上（两项差异都为零
自然直接通过）；任一差异超出允许范围，复核对不上就必须说明原因并退回理货岗返工。

约束：
- 理货人员缺失或理货箱量为空（含非数字）的单据判为「资料不齐」单独挑出，不进入复核；
- 同一张理货单重复复核只留最新一条结论（按 tally_id 覆盖）；
- 差异始终按理货单当前数据重算，刷新后结论快照与理货单对不上的标「已变更待重核」。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.tally import TallyService
from app.store import store

MODULE = "tally_review"
TALLY_MODULE = "tally"

# 允许范围：箱量相差不超过 2 箱、残损箱数必须一致。
BOX_TOLERANCE = 2
DAMAGE_TOLERANCE = 0

JUDGE_INCOMPLETE = "资料不齐"
JUDGE_PENDING = "待复核"
JUDGE_APPROVED = "复核通过"
JUDGE_RETURNED = "复核退回"
JUDGE_STALE = "已变更待重核"
JUDGE_LABELS = [
    JUDGE_PENDING,
    JUDGE_INCOMPLETE,
    JUDGE_STALE,
    JUDGE_APPROVED,
    JUDGE_RETURNED,
]

RESULT_PASS = "通过"
RESULT_RETURN = "退回"

tally_service = TallyService()


def _to_int(value: Any) -> int | None:
    """把箱量字段收成整数；空值与非数字一律视为未填（None）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


class TallyReviewService:
    def tolerance(self) -> dict[str, int]:
        """对外暴露同一条判定口径，页面提示与后端判定取同一处常量。"""
        return {"箱量允许差异": BOX_TOLERANCE, "残损箱数允许差异": DAMAGE_TOLERANCE}

    def _missing_fields(self, tally: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        if not str(tally.get("理货人员") or "").strip():
            missing.append("理货人员")
        if _to_int(tally.get("理货箱量")) is None:
            missing.append("理货箱量")
        return missing

    def _within_tolerance(self, box_diff: int, damage_diff: int) -> bool:
        return abs(box_diff) <= BOX_TOLERANCE and abs(damage_diff) <= DAMAGE_TOLERANCE

    def latest_conclusion(self, tally_id: int) -> dict[str, Any] | None:
        rows = [row for row in store.rows(MODULE) if int(row.get("tally_id", 0)) == tally_id]
        return rows[-1] if rows else None

    def build_view(self, tally: dict[str, Any]) -> dict[str, Any]:
        """把理货单与最新复核结论拼成一行工作台视图；差异每次重算，不存旧值。"""
        box = _to_int(tally.get("理货箱量"))
        damage = _to_int(tally.get("残损箱数")) or 0
        missing = self._missing_fields(tally)

        view: dict[str, Any] = {
            "id": int(tally.get("id", 0)),
            "理货单号": tally.get("理货单号"),
            "关联航次": tally.get("关联航次"),
            "理货方式": tally.get("理货方式"),
            "理货箱量": tally.get("理货箱量"),
            "残损箱数": damage,
            "理货人员": tally.get("理货人员"),
            "理货状态": tally.get("status"),
            "资料齐": not missing,
            "缺失项": missing,
            "随附箱量": None,
            "随附残损数": None,
            "箱量差异": None,
            "残损差异": None,
            "在允许范围": None,
            "判定": JUDGE_INCOMPLETE if missing else JUDGE_PENDING,
            "复核结论": None,
            "复核原因": None,
            "复核人员": None,
            "复核时间": None,
            "与理货单一致": None,
        }

        conclusion = self.latest_conclusion(view["id"])
        if conclusion is None or missing:
            return view

        attached_box = _to_int(conclusion.get("随附箱量")) or 0
        attached_damage = _to_int(conclusion.get("随附残损数")) or 0
        # 差异始终按理货单当前数据与随附记录重算，刷新后看到的就是最新口径结果。
        box_diff = (box or 0) - attached_box
        damage_diff = damage - attached_damage
        consistent = (
            _to_int(conclusion.get("理货箱量快照")) == box
            and _to_int(conclusion.get("残损箱数快照")) == damage
        )

        view.update(
            {
                "随附箱量": attached_box,
                "随附残损数": attached_damage,
                "箱量差异": box_diff,
                "残损差异": damage_diff,
                "在允许范围": self._within_tolerance(box_diff, damage_diff),
                "复核结论": conclusion.get("复核结论"),
                "复核原因": conclusion.get("复核原因"),
                "复核人员": conclusion.get("复核人员"),
                "复核时间": conclusion.get("复核时间"),
                "与理货单一致": consistent,
            }
        )
        if not consistent:
            view["判定"] = JUDGE_STALE
        elif conclusion.get("复核结论") == RESULT_PASS:
            view["判定"] = JUDGE_APPROVED
        else:
            view["判定"] = JUDGE_RETURNED
        return view

    def list_worklist(
        self,
        *,
        keyword: str | None = None,
        judge: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        views = [self.build_view(row) for row in store.rows(TALLY_MODULE)]
        if keyword:
            views = [row for row in views if keyword in str(row.get("理货单号") or "")]
        if judge:
            views = [row for row in views if row["判定"] == judge]
        total = len(views)
        start = max(page - 1, 0) * size
        return views[start:start + size], total

    def summary(self) -> dict[str, Any]:
        views = [self.build_view(row) for row in store.rows(TALLY_MODULE)]
        counts = {label: 0 for label in JUDGE_LABELS}
        for row in views:
            counts[row["判定"]] += 1
        return {"total": len(views), "counts": counts, "允许范围": self.tolerance()}

    def submit_review(
        self, tally_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """提交一次复核。返回 (视图, 说明, 是否通过)；校验不过时视图为 None。"""
        tally = store.find(TALLY_MODULE, tally_id)
        if tally is None:
            return None, f"理货单 {tally_id} 不存在或已归档", False

        missing = self._missing_fields(tally)
        if missing:
            return None, f"该理货单{'、'.join(missing)}缺失，已归入「资料不齐」，请补齐后再复核", False

        reviewer = str(values.get("复核人员") or "").strip()
        if not reviewer:
            return None, "复核人员不能为空", False

        attached_box = _to_int(values.get("随附箱量"))
        if attached_box is None:
            return None, "随附记录箱量不能为空且须为整数", False
        attached_damage = _to_int(values.get("随附残损数")) or 0

        box = _to_int(tally.get("理货箱量")) or 0
        damage = _to_int(tally.get("残损箱数")) or 0
        box_diff = box - attached_box
        damage_diff = damage - attached_damage

        if self._within_tolerance(box_diff, damage_diff):
            result, reason = RESULT_PASS, ""
        else:
            reason = str(values.get("复核原因") or "").strip()
            if not reason:
                return None, (
                    f"差异超出允许范围（箱量差 {box_diff} 箱、残损差 {damage_diff} 箱，"
                    f"允许范围分别为 ±{BOX_TOLERANCE} 箱、{DAMAGE_TOLERANCE} 箱），"
                    "复核对不上须填写原因并退回"
                ), False
            result = RESULT_RETURN

        # 同一理货单只留最新一条结论：已有结论就原位覆盖。
        rows = store.rows(MODULE)
        conclusion = {
            "tally_id": tally_id,
            "随附箱量": attached_box,
            "随附残损数": attached_damage,
            "箱量差异": box_diff,
            "残损差异": damage_diff,
            "理货箱量快照": box,
            "残损箱数快照": damage,
            "复核结论": result,
            "复核原因": reason,
            "复核人员": reviewer,
            "复核时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pending": result == RESULT_RETURN,
            "abnormal": result == RESULT_RETURN,
        }
        for index, row in enumerate(rows):
            if int(row.get("tally_id", 0)) == tally_id:
                conclusion["id"] = row.get("id")
                rows[index] = conclusion
                break
        else:
            conclusion["id"] = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            rows.append(conclusion)

        if result == RESULT_PASS:
            tally_service.apply_review_result(tally, passed=True)
            if box_diff == 0 and damage_diff == 0:
                message = "箱量、残损箱数与随附记录完全一致，差异为零，复核通过，理货单直接结单"
            else:
                message = (
                    f"箱量差 {box_diff} 箱、残损差 {damage_diff} 箱，在允许范围内，"
                    "复核通过，理货单准予结单"
                )
        else:
            tally_service.apply_review_result(tally, passed=False)
            message = (
                f"箱量差 {box_diff} 箱、残损差 {damage_diff} 箱，超出允许范围，"
                "已记录原因并退回理货岗返工"
            )
        return self.build_view(tally), message, result == RESULT_PASS
