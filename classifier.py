"""
키워드 분류 로직 - 상위 10위 유형 분석 기반

분류 기준:
- 상위 10개 콘텐츠에서 유형(블로그/카페/인플루언서/지식인) 분포 분석
- 3개월 이내 발행 + 동일 유형 3개 이상 → 해당 유형으로 추천
- 지식인: 2개 이상이면 추천 (발행일 무시)
- 동일 유형이 많을수록 키워드 우선순위 상승
"""

import re
from datetime import datetime, timedelta

from models import KeywordResult, BlockType, EXCLUDED_BLOCKS


TARGET_TYPES = ["블로그", "카페", "인플루언서", "지식인"]


def get_content_type(url: str) -> str:
    """URL 패턴으로 콘텐츠 유형 판별"""
    if not url:
        return "기타"
    if "blog.naver.com" in url or "post.naver.com" in url or "m.blog.naver.com" in url:
        return "블로그"
    if "cafe.naver.com" in url or "m.cafe.naver.com" in url:
        return "카페"
    if "://kin.naver.com" in url:
        return "지식인"
    if "://in.naver.com" in url:
        return "인플루언서"
    return "기타"


def parse_date(date_str: str) -> datetime | None:
    """날짜 문자열을 datetime으로 변환"""
    if not date_str:
        return None

    match = re.match(r'(\d{4})\.(\d{2})\.(\d{2})', date_str)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    now = datetime.now()
    match = re.match(r'(\d+)분\s*전', date_str)
    if match:
        return now - timedelta(minutes=int(match.group(1)))

    match = re.match(r'(\d+)시간\s*전', date_str)
    if match:
        return now - timedelta(hours=int(match.group(1)))

    match = re.match(r'(\d+)일\s*전', date_str)
    if match:
        return now - timedelta(days=int(match.group(1)))

    match = re.match(r'(\d+)주\s*전', date_str)
    if match:
        return now - timedelta(weeks=int(match.group(1)))

    match = re.match(r'(\d+)개월\s*전', date_str)
    if match:
        return now - timedelta(days=int(match.group(1)) * 30)

    return None


def is_recent(date_str: str, months: int = 3) -> bool | None:
    """날짜가 최근 N개월 이내인지 확인. None이면 판별 불가."""
    dt = parse_date(date_str)
    if dt is None:
        return None
    cutoff = datetime.now() - timedelta(days=months * 30)
    return dt >= cutoff


def get_top10_items(result: KeywordResult) -> list:
    """키워드의 상위 10개 콘텐츠 아이템 추출 (블록 순서대로)"""
    items = []
    for block in result.smart_blocks:
        if block.block_type in EXCLUDED_BLOCKS:
            continue
        for item in block.items:
            items.append(item)
    return items[:10]


def analyze_keyword(result: KeywordResult) -> dict:
    """
    키워드 1개의 상위 10위 유형 분석.

    Returns:
        {
            "type_counts": {"블로그": N, ...},          # 상위 10위 내 유형별 전체 개수
            "type_recent_counts": {"블로그": N, ...},   # 3개월 이내 유형별 개수 (지식인은 전체)
            "recommended_types": ["카페", ...],         # 추천 유형 목록
        }
    """
    top10 = get_top10_items(result)

    type_counts = {t: 0 for t in TARGET_TYPES}
    type_recent_counts = {t: 0 for t in TARGET_TYPES}

    for item in top10:
        content_type = get_content_type(item.url)
        if content_type not in TARGET_TYPES:
            continue
        type_counts[content_type] += 1
        if content_type == "지식인":
            # 지식인은 날짜 무시 → recent count = total count
            type_recent_counts[content_type] += 1
        else:
            recent = is_recent(item.date)
            if recent is True:
                type_recent_counts[content_type] += 1

    # 추천 유형 결정
    recommended = []
    for ctype in TARGET_TYPES:
        if ctype == "지식인":
            if type_counts[ctype] >= 2:
                recommended.append(ctype)
        else:
            if type_recent_counts[ctype] >= 3:
                recommended.append(ctype)

    # 추천 유형 정렬: 해당 유형 개수가 많은 순
    recommended.sort(key=lambda t: type_recent_counts[t], reverse=True)

    return {
        "type_counts": type_counts,
        "type_recent_counts": type_recent_counts,
        "recommended_types": recommended,
    }


def classify_all(results: dict) -> dict:
    """전체 키워드 분류 실행. KeywordResult.recommended_types와 classification 업데이트.

    Returns:
        {keyword: analysis_dict} - 키워드별 분석 결과
    """
    analyses = {}
    for keyword, result in results.items():
        if isinstance(result, KeywordResult) and result.crawled_at:
            analysis = analyze_keyword(result)
            result.recommended_types = analysis["recommended_types"]
            result.classification = "/".join(analysis["recommended_types"]) if analysis["recommended_types"] else ""
            analyses[keyword] = analysis
    return analyses


def get_keywords_by_type(results: dict, analyses: dict | None = None) -> dict:
    """유형별 키워드 목록 (우선순위: 해당 유형 아이템 수가 많을수록 상위)

    Args:
        results: {keyword: KeywordResult} 딕셔너리
        analyses: 이미 계산된 {keyword: analysis_dict}. None이면 내부에서 계산.

    Returns:
        {
            "블로그": [(keyword, count), ...],
            "카페": [(keyword, count), ...],
            "인플루언서": [(keyword, count), ...],
            "지식인": [(keyword, count), ...],
        }
    """
    by_type = {t: [] for t in TARGET_TYPES}

    for keyword, result in results.items():
        if not isinstance(result, KeywordResult) or not result.crawled_at:
            continue
        if not result.recommended_types:
            continue
        analysis = (analyses or {}).get(keyword) or analyze_keyword(result)
        for ctype in result.recommended_types:
            if ctype == "지식인":
                count = analysis["type_counts"][ctype]
            else:
                count = analysis["type_recent_counts"][ctype]
            by_type[ctype].append((keyword, count))

    for ctype in by_type:
        by_type[ctype].sort(key=lambda x: x[1], reverse=True)

    return by_type
