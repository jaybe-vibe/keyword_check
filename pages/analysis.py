"""페이지 3: 분석 결과"""

import streamlit as st
import pandas as pd

from classifier import (
    classify_all, analyze_keyword, get_content_type, is_recent,
    get_top10_items, TARGET_TYPES, is_momsholic,
)
from utils.keyword_utils import get_crawled_results, is_duplicate_keyword, add_keywords


def render():
    st.header("📊 분석 결과")

    crawled_results = get_crawled_results(st.session_state.results)

    if not crawled_results:
        st.warning("🌐 네이버 크롤링을 먼저 실행해주세요.")
        return

    st.success(f"분석된 키워드: {len(crawled_results)}개")

    # 분류 실행 + 캐싱
    analyses = _get_cached_analyses()

    _render_type_analysis(crawled_results, analyses)

    st.subheader("키워드별 상세 결과")
    _render_keyword_detail(crawled_results, analyses)


def _get_cached_analyses() -> dict:
    """classify_all 결과 (매번 재계산하여 크롤링 후 갱신 보장)"""
    analyses = classify_all(st.session_state.results)
    st.session_state.cached_analyses = analyses
    return analyses


def _render_type_analysis(crawled_results, analyses):
    """키워드별 상위 10위 유형 분석"""
    st.subheader("키워드별 상위 10위 유형 분석")
    st.caption(
        "추천 조건: 블로그/카페/인플루언서 - 상위 10위 내 동일 유형 3개 이상 & 3개월 이내 발행 | "
        "지식인 - 상위 10위 내 2개 이상 (날짜 무시)"
    )

    analysis_data = []
    for kw, result in crawled_results.items():
        analysis = analyses.get(kw, analyze_keyword(result))
        tc = analysis["type_counts"]
        trc = analysis["type_recent_counts"]
        row = {
            "키워드": kw,
            "블로그": f"{tc['블로그']} ({trc['블로그']}추천)" if tc["블로그"] > 0 else "0",
            "카페": f"{tc['카페']} ({trc['카페']}추천)" if tc["카페"] > 0 else "0",
            "맘스홀릭": str(tc.get("맘스홀릭", 0)),
            "인플루언서": f"{tc['인플루언서']} ({trc['인플루언서']}추천)" if tc["인플루언서"] > 0 else "0",
            "지식인": str(tc["지식인"]),
            "추천유형": "/".join(analysis["recommended_types"]) if analysis["recommended_types"] else "-",
        }
        analysis_data.append(row)

    st.dataframe(pd.DataFrame(analysis_data), use_container_width=True, hide_index=True)


def _render_keyword_detail(crawled_results, analyses):
    """키워드별 상세 결과"""
    selected_kw = st.selectbox("키워드 선택", list(crawled_results.keys()))

    if not selected_kw:
        return

    result = crawled_results[selected_kw]
    analysis = analyses.get(selected_kw, analyze_keyword(result))

    tc = analysis["type_counts"]
    trc = analysis["type_recent_counts"]
    icons = {"블로그": "📝", "카페": "☕", "맘스홀릭": "🤰", "인플루언서": "⭐", "지식인": "❓"}
    cols = st.columns(5)
    for col, ctype in zip(cols, TARGET_TYPES):
        if ctype == "지식인":
            label = f"{tc[ctype]}개"
        elif ctype == "맘스홀릭":
            label = f"{tc.get(ctype, 0)}개"
        else:
            label = f"{tc[ctype]}개 (추천 {trc[ctype]})"
        col.metric(f"{icons[ctype]} {ctype}", label)

    recommended = analysis["recommended_types"]
    if recommended:
        st.info(f"추천유형: **{'/'.join(recommended)}**")

    top10 = get_top10_items(result)
    if top10:
        st.write("**상위 10위 콘텐츠**")
        detail_data = []
        for rank, item in enumerate(top10, 1):
            ctype = get_content_type(item.url)
            # 맘스홀릭이면 유형에 표시
            if ctype == "카페" and is_momsholic(item.url):
                ctype = "카페(맘스홀릭)"
            recent = is_recent(item.date)
            detail_data.append({
                "순위": rank,
                "유형": ctype,
                "제목": item.title,
                "출처": item.source or "-",
                "날짜": item.date or "-",
                "추천": "추천" if recent is True else "",
            })
        st.dataframe(
            pd.DataFrame(detail_data), use_container_width=True, hide_index=True,
            column_config={"순위": st.column_config.NumberColumn(width="small")},
        )

    # 연관키워드 표시 (API dict 또는 HTML str 모두 대응)
    display_related = []
    for rk in result.related_keywords:
        if isinstance(rk, dict):
            display_related.append(rk.get("keyword", ""))
        elif isinstance(rk, str):
            display_related.append(rk)
    if not display_related:
        display_related = list(result.related_keywords_html)

    if display_related:
        st.subheader("함께 많이 찾는 키워드")
        cols = st.columns(min(len(display_related), 4))
        for i, rk in enumerate(display_related):
            if not rk:
                continue
            with cols[i % len(cols)]:
                already_in = is_duplicate_keyword(rk, st.session_state.keywords)
                if already_in:
                    st.write(f"✅ {rk}")
                else:
                    if st.button(f"➕ {rk}", key=f"add_related_{selected_kw}_{i}"):
                        added, _ = add_keywords([rk])
                        if added:
                            st.success(f"'{added[0]}' 추가됨")
                            st.rerun()
