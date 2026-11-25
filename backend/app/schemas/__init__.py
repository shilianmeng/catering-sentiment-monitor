"""请求体模型（Pydantic）：接口入参的类型、取值范围在这里声明，格式错误统一返回 422。

业务规则校验（如状态机、S>A>B）在 service 层做，违反时返回 400/409。
"""
from typing import Optional, Union

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field("", max_length=64)
    password: str = Field("", max_length=128)


class LevelIn(BaseModel):
    level: str = Field("", description="S / A / B / C，或 auto 恢复自动评级")
    reason: str = Field("", max_length=500, description="改级理由，必填")


class DisposalIn(BaseModel):
    to_status: str = ""
    note: str = Field("", max_length=500)


class DraftAdoptIn(BaseModel):
    draft_id: Optional[int] = None


class TopicCreate(BaseModel):
    name: str = Field("", max_length=100)
    keywords: Union[str, list[str]] = Field(default_factory=list, description="列表，或用逗号分隔的字符串")
    channels: dict[str, bool] = Field(default_factory=dict)
    brand: Optional[str] = Field(None, max_length=100, description="品牌名，留空取第一个关键词")
    entities: Optional[list] = Field(None, description="品牌自有实体 [{name,type,aliases}]")
    event_rules: Optional[list] = Field(None, description="议题规则 [{category,title,keywords}]，留空走行业默认")
    enabled: bool = True


class TopicUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    keywords: Optional[Union[str, list[str]]] = None
    channels: Optional[dict[str, bool]] = None
    brand: Optional[str] = Field(None, max_length=100)
    entities: Optional[list] = None
    event_rules: Optional[list] = None
    enabled: Optional[bool] = None


class StoreCreate(BaseModel):
    topic_id: int
    name: str = Field("", max_length=100, description="门店全称，如「品牌·某某路店」")
    aliases: list[str] = Field(default_factory=list, description="文本里的其他叫法")
    ownership: str = Field("直营", description="直营 / 加盟")
    province: Optional[str] = Field(None, max_length=50)
    city: Optional[str] = Field(None, max_length=50)
    district: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=200)
    license_subject: Optional[str] = Field(None, max_length=200, description="营业执照经营主体")
    status: str = Field("营业", description="营业 / 停业整改 / 已关店")


class StoreUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    aliases: Optional[list[str]] = None
    ownership: Optional[str] = None
    province: Optional[str] = Field(None, max_length=50)
    city: Optional[str] = Field(None, max_length=50)
    district: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=200)
    license_subject: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = None


class CollectIn(BaseModel):
    source_id: str
    pages: int = Field(3, ge=1, le=50, description="翻几页列表；每页约 100 篇公告")


class ConfigUpdate(BaseModel):
    surge_threshold: Optional[int] = Field(None, ge=1, le=10000)
    surge_min_count: Optional[int] = Field(None, ge=1, le=1000)
    level_s: Optional[int] = Field(None, ge=1, le=100)
    level_a: Optional[int] = Field(None, ge=1, le=100)
    level_b: Optional[int] = Field(None, ge=1, le=100)
    silence_minutes: Optional[int] = Field(None, ge=0, le=1440)
    kol_alert_weight: Optional[int] = Field(None, ge=1, le=10)
    notify_site: Optional[bool] = None
    notify_email: Optional[bool] = None
    notify_sms: Optional[bool] = None


class AdvanceIn(BaseModel):
    batches: int = Field(1, ge=1, le=20)
