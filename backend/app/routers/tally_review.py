"""理货差异复核接口：理货单与随附记录对箱量、残损箱数，一条口径定结论。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.tally_review import JUDGE_LABELS, TallyReviewService

router = APIRouter(prefix="/api/tally-review", tags=["理货差异复核"])

service = TallyReviewService()


@router.get("/tolerance")
def get_tolerance() -> dict[str, Any]:
    """查看唯一一条差异判定口径：箱量允许差异、残损箱数允许差异。"""
    return service.tolerance()


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    """复核工作台汇总：总数与各判定口径下的单据数，供页面统计卡片使用。"""
    return service.summary()


@router.get("", response_model=PageResult[dict])
def list_worklist(
    keyword: str | None = Query(default=None, description="按理货单号检索"),
    judge: str | None = Query(default=None, description="待复核、资料不齐、已变更待重核、复核通过、复核退回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """列出复核工作台：差异按理货单当前数据实时重算；结论刷新后与理货单保持一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if judge and judge not in JUDGE_LABELS:
        raise HTTPException(status_code=400, detail=f"判定口径仅支持：{'、'.join(JUDGE_LABELS)}")
    items, total = service.list_worklist(keyword=keyword, judge=judge, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/{tally_id}/review", response_model=ActionResult)
def submit_review(tally_id: int, payload: EntryPayload) -> ActionResult:
    """对一张理货单提交复核结论：差异在允许范围内直接通过结单；超出范围须填原因退回。

    同一张理货单重复复核只留最新一条结论；理货人员缺失或理货箱量为空的单据会被拦下。
    """
    view, message, ok = service.submit_review(tally_id, payload.values)
    return ActionResult(ok=ok, message=message, entry=view)


@router.get("/export")
def export_worklist() -> dict[str, Any]:
    """导出理货差异复核台账：返回当前全部理货单的最新复核结论。"""
    items, total = service.list_worklist(page=1, size=10000)
    return {"module": "tally_review", "total": total, "items": items}
