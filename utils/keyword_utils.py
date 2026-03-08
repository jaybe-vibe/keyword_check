"""키워드 유틸리티 함수 - 정규화, 중복 확인, 추가"""

import re
import streamlit as st


def normalize_keyword(kw: str) -> str:
    """키워드 정규화: 공백 제거"""
    return kw.replace(" ", "").strip()


def is_duplicate_keyword(kw: str, existing: list[str]) -> bool:
    """공백 제거 기준 중복 확인 (set 기반 O(1) 조회)"""
    normalized = normalize_keyword(kw)
    existing_set = {normalize_keyword(e) for e in existing}
    return normalized in existing_set


def add_keywords(raw_keywords: list[str]) -> tuple[list[str], list[str]]:
    """키워드 추가. 공백 제거 + 중복 방지. (추가된 목록, 중복 목록) 반환"""
    added = []
    duplicates = []
    existing_set = {normalize_keyword(k) for k in st.session_state.keywords}
    for kw in raw_keywords:
        normalized = normalize_keyword(kw)
        if not normalized:
            continue
        if normalized in existing_set:
            duplicates.append(kw)
        else:
            st.session_state.keywords.append(normalized)
            existing_set.add(normalized)
            added.append(normalized)
    return added, duplicates


def get_crawled_results(results: dict) -> dict:
    """크롤링 완료된 결과만 필터링"""
    from models import KeywordResult
    return {
        kw: r for kw, r in results.items()
        if isinstance(r, KeywordResult) and r.crawled_at
    }


def sanitize_filename(keyword: str) -> str:
    """키워드를 안전한 파일명으로 변환"""
    return re.sub(r'[^a-zA-Z0-9가-힣_\-]', '_', keyword)
