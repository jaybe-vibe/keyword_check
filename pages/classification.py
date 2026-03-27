"""페이지 4: 키워드 분류"""

import streamlit as st
import pandas as pd

from models import KeywordResult
from classifier import classify_all, get_keywords_by_type, TARGET_TYPES
from utils.keyword_utils import get_crawled_results


def render():
    st.header("🏷️ 키워드 분류")
    st.caption(
        "블로그/카페/인플루언서: 상위 10위 내 3개 이상 & 3개월 이내 → 추천 | "
        "지식인: 상위 10위 내 2개 이상 → 추천 | "
        "동일 유형이 많을수록 우선순위 상승"
    )

    crawled_results = get_crawled_results(st.session_state.results)

    if not crawled_results:
        st.warning("🌐 네이버 크롤링을 먼저 실행해주세요.")
        return

    # 분류 결과 (매번 재계산하여 크롤링 후 갱신 보장)
    analyses = classify_all(st.session_state.results)
    st.session_state.cached_analyses = analyses

    by_type = get_keywords_by_type(st.session_state.results, analyses)

    icons = {"블로그": "📝", "카페": "☕", "맘스홀릭": "🤰", "인플루언서": "⭐", "지식인": "❓"}

    for ctype in TARGET_TYPES:
        kw_list = by_type.get(ctype, [])
        st.subheader(f"{icons[ctype]} {ctype} 추천 키워드 ({len(kw_list)}개)")
        if kw_list:
            type_data = []
            for rank, (kw, count) in enumerate(kw_list, 1):
                result = st.session_state.results.get(kw)
                vol = result.search_volume_total if isinstance(result, KeywordResult) else 0
                type_data.append({
                    "우선순위": rank,
                    "키워드": kw,
                    "해당유형 수": count,
                    "총 검색량": vol,
                    "추천유형": result.classification if isinstance(result, KeywordResult) else "",
                })
            st.dataframe(
                pd.DataFrame(type_data), use_container_width=True, hide_index=True,
                column_config={
                    "우선순위": st.column_config.NumberColumn(width="small"),
                    "총 검색량": st.column_config.NumberColumn(format="%d"),
                },
            )
        else:
            st.info(f"{ctype} 추천 키워드 없음")

    st.divider()
    st.subheader("전체 분류 결과")
    class_data = []
    for kw in st.session_state.keywords:
        result = st.session_state.results.get(kw)
        if isinstance(result, KeywordResult) and result.crawled_at:
            analysis = analyses.get(kw, {})
            tc = analysis.get("type_counts", {"블로그": 0, "카페": 0, "맘스홀릭": 0, "인플루언서": 0, "지식인": 0})
            class_data.append({
                "키워드": kw,
                "추천유형": result.classification or "-",
                "블로그": tc.get("블로그", 0),
                "카페": tc.get("카페", 0),
                "맘스홀릭": tc.get("맘스홀릭", 0),
                "인플루언서": tc.get("인플루언서", 0),
                "지식인": tc.get("지식인", 0),
                "총 검색량": result.search_volume_total,
            })
    if class_data:
        st.dataframe(
            pd.DataFrame(class_data), use_container_width=True, hide_index=True,
            column_config={"총 검색량": st.column_config.NumberColumn(format="%d")},
        )
