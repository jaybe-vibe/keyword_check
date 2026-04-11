"""
데이터 모델 정의 - 네이버 키워드 분석 도구

모든 모듈이 공유하는 데이터 클래스와 상수 정의.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class BlockType(str, Enum):
    """네이버 스마트블록 유형"""
    BLOG = "블로그"
    CAFE = "카페"
    INFLUENCER = "인플루언서"
    KNOWLEDGE = "지식인"
    NEWS = "뉴스"
    IMAGE = "이미지"
    VIDEO = "동영상"
    VIEW = "VIEW"
    PLACE = "플레이스"
    BRAND = "브랜드콘텐츠"
    SHOPPING = "쇼핑"
    POWERLINK = "파워링크"
    NAVER_STORE = "네이버플러스 스토어"
    PRICE_COMPARE = "가격비교"
    OTHER = "기타"


# 분석에서 제외할 블록
EXCLUDED_BLOCKS = {
    BlockType.POWERLINK,
    BlockType.SHOPPING,
    BlockType.NAVER_STORE,
    BlockType.PRICE_COMPARE,
}

# 상세 콘텐츠를 추출할 우선 블록
PRIORITY_BLOCKS = {
    BlockType.BLOG,
    BlockType.CAFE,
    BlockType.INFLUENCER,
    BlockType.KNOWLEDGE,
}


@dataclass
class ContentItem:
    """스마트블록 내 개별 콘텐츠 항목"""
    title: str = ""
    url: str = ""
    source: str = ""
    date: str = ""
    description: str = ""
    rank: int = 0


@dataclass
class SmartBlock:
    """검색 결과의 스마트블록 섹션"""
    block_type: BlockType = BlockType.OTHER
    block_name: str = ""
    position: int = 0
    items: list[ContentItem] = field(default_factory=list)
    item_count: int = 0


@dataclass
class KeywordResult:
    """키워드 1개에 대한 전체 분석 결과"""
    keyword: str = ""
    search_volume_pc: int = 0
    search_volume_mobile: int = 0
    search_volume_total: int = 0
    competition: str = ""
    # 월평균 클릭수
    avg_pc_clicks: float = 0.0
    avg_mobile_clicks: float = 0.0
    # 월평균 클릭률 (%)
    avg_pc_ctr: float = 0.0
    avg_mobile_ctr: float = 0.0
    # 월평균 노출 광고수
    avg_ad_count: float = 0.0
    smart_blocks: list[SmartBlock] = field(default_factory=list)
    related_keywords: list[dict] = field(default_factory=list)  # API 연관키워드 [{keyword, pc, mobile, total, competition, ...}]
    related_keywords_html: list[str] = field(default_factory=list)  # HTML 파싱 연관키워드 (보조)
    classification: str = ""
    recommended_types: list[str] = field(default_factory=list)
    crawled_at: Optional[datetime] = None
    error: str = ""
