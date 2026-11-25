"""主体风险（营业执照主体 = 统一社会信用代码）。只读，所有角色可看。"""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ....services import subject_risk_service
from ...deps import DB, CurrentUser

router = APIRouter(prefix="/subjects", tags=["主体风险"])


@router.get("/risk", summary="主体风险排名：按信用代码归并官方处罚，可按违法类别、等级筛选")
def ranking(source_id: Optional[str] = None, as_of: Optional[str] = None, category: Optional[str] = None,
            level: Optional[str] = None, limit: int = Query(50, ge=0, le=1000), user=CurrentUser, conn=DB):
    return subject_risk_service.ranking(conn, source_id, as_of, category, level, limit or None)


@router.get("/profile", summary="区域画像：违法类别、处罚档次、年份、处罚机关分布，罚款最高与反复被罚的主体")
def profile(source_id: Optional[str] = None, as_of: Optional[str] = None, top: int = Query(10, ge=1, le=100),
            user=CurrentUser, conn=DB):
    return subject_risk_service.district_profile(conn, source_id, as_of, top)


@router.get("/{key}/report", summary="单主体体检报告（第④步）：结论、处罚记录、评分拆解、整改建议")
def report(key: str, source_id: Optional[str] = None, as_of: Optional[str] = None, user=CurrentUser, conn=DB):
    return subject_risk_service.health_report(conn, key, source_id, as_of)


@router.get("/{key}/report/export", summary="导出体检报告 Markdown / PDF")
def export_report(key: str, format: str = Query("md", pattern="^(md|pdf)$"), source_id: Optional[str] = None,
                  as_of: Optional[str] = None, user=CurrentUser, conn=DB):
    data, media_type, filename = subject_risk_service.export_report(conn, key, format, source_id, as_of)
    return Response(data, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename=\"report.{format}\"; "
                                                    f"filename*=UTF-8''{quote(filename)}"})


@router.get("/{key}/risk", summary="单主体风险明细：每条处罚的档位、衰减、得分理由、类别和原文链接")
def detail(key: str, source_id: Optional[str] = None, as_of: Optional[str] = None, user=CurrentUser, conn=DB):
    return subject_risk_service.subject_detail(conn, key, source_id, as_of)
