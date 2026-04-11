"""페이지 2: 네이버 크롤링"""

import threading
import streamlit as st
import pandas as pd

from models import KeywordResult
from utils.crawl_runner import run_crawl_thread


def render():
    st.header("🌐 네이버 크롤링")

    if not st.session_state.keywords:
        st.warning("📋 키워드 관리 페이지에서 먼저 키워드를 입력해주세요.")
        return

    # 크롤링 대상 키워드 선택 (전체 vs 필터된 키워드)
    filtered = st.session_state.get("filtered_keywords", [])
    all_kws = st.session_state.keywords
    has_active_filter = filtered and len(filtered) < len(all_kws)

    if has_active_filter:
        crawl_mode = st.radio(
            "크롤링 대상",
            [f"전체 키워드 ({len(all_kws)}개)", f"필터된 키워드 ({len(filtered)}개)"],
            horizontal=True,
        )
        target_keywords = filtered if "필터" in crawl_mode else all_kws
    else:
        target_keywords = all_kws

    st.info(f"분석 대상: {len(target_keywords)}개 키워드")

    config = st.session_state.config

    shared = st.session_state.crawl_shared

    _render_controls(
        shared,
        config.get("headed", False),
        float(config.get("min_delay", 5.0)),
        float(config.get("max_delay", 12.0)),
        int(config.get("context_rotation_interval", 12)),
        target_keywords,
    )

    st.divider()
    _render_progress(shared)
    _render_crawl_log(shared)

    st.divider()
    _render_results_summary()


def _render_controls(shared, headed, min_delay, max_delay, rotation, target_keywords):
    """크롤링 제어 버튼"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        start_disabled = shared["status"] in ("running", "paused")
        if st.button("크롤링 시작", type="primary", disabled=start_disabled):
            shared["status"] = "running"
            shared["progress"] = 0.0
            shared["completed"] = 0
            shared["log"] = []
            shared["stop_signal"] = False
            shared["pause_signal"] = False
            shared["current"] = ""
            shared["total"] = len(target_keywords)
            shared["target_keywords"] = list(target_keywords)

            thread = threading.Thread(
                target=run_crawl_thread,
                args=(
                    list(target_keywords),
                    {
                        "headed": headed,
                        "min_delay": min_delay,
                        "max_delay": max_delay,
                        "context_rotation_interval": rotation,
                    },
                    shared,
                    st.session_state.results,
                ),
                daemon=True,
            )
            thread.start()
            st.rerun()

    with col2:
        if st.button("일시정지", disabled=shared["status"] != "running"):
            shared["pause_signal"] = True
            shared["status"] = "paused"

    with col3:
        if st.button("재개", disabled=shared["status"] != "paused"):
            shared["pause_signal"] = False
            shared["status"] = "running"

    with col4:
        if st.button("중지", disabled=shared["status"] not in ("running", "paused")):
            shared["stop_signal"] = True
            shared["status"] = "idle"


def _render_progress(shared):
    """진행 상태 표시"""
    if shared["status"] in ("running", "paused"):
        total = shared.get("total", len(st.session_state.keywords))
        completed = shared["completed"]
        progress = completed / total if total > 0 else 0

        st.progress(progress, text=f"진행: {completed}/{total} ({progress*100:.0f}%)")

        if shared["current"]:
            st.write(f"현재 키워드: **{shared['current']}**")

        if shared["log"]:
            with st.expander("크롤링 로그", expanded=True):
                for log_entry in shared["log"][-30:]:
                    st.text(log_entry)

        # 자동 새로고침 (st.rerun 대신 autorefresh 사용, 블로킹 없음)
        st.rerun()

    elif shared["status"] == "completed":
        st.success("크롤링 완료!")
        completed = shared["completed"]
        total = shared.get("total", len(st.session_state.keywords))
        errors = sum(
            1 for r in st.session_state.results.values()
            if isinstance(r, KeywordResult) and r.error
        )
        st.write(f"완료: {completed}/{total}개 | 오류: {errors}개")

    elif shared["status"] == "error":
        st.error("크롤링 오류 발생!")


def _render_crawl_log(shared):
    """크롤링 로그 (완료/에러 상태)"""
    if shared["status"] in ("completed", "error", "idle") and shared["log"]:
        log_expanded = shared["status"] == "error"
        with st.expander("크롤링 로그", expanded=log_expanded):
            for log_entry in shared["log"][-50:]:
                st.text(log_entry)


def _render_results_summary():
    """키워드별 크롤링 결과 요약"""
    st.subheader("키워드별 크롤링 결과")

    crawled_data = []
    for kw in st.session_state.keywords:
        result = st.session_state.results.get(kw)
        if isinstance(result, KeywordResult) and result.crawled_at:
            block_names = [b.block_name for b in result.smart_blocks]
            crawled_data.append({
                "키워드": kw,
                "스마트블록": ", ".join(block_names) if block_names else "-",
                "블록 수": len(result.smart_blocks),
                "연관키워드": len(result.related_keywords) or len(result.related_keywords_html),
                "오류": result.error or "-",
            })

    if crawled_data:
        st.dataframe(pd.DataFrame(crawled_data), use_container_width=True, hide_index=True)
    else:
        st.info("아직 크롤링된 키워드가 없습니다.")
