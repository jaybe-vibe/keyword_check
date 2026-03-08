"""공통 Streamlit UI 컴포넌트"""

import streamlit as st


# 검색량 테이블 공통 column_config
VOLUME_COLUMN_CONFIG = {
    "PC": st.column_config.NumberColumn(format="%d"),
    "모바일": st.column_config.NumberColumn(format="%d"),
    "합계": st.column_config.NumberColumn(format="%d"),
    "PC클릭수": st.column_config.NumberColumn(format="%.1f"),
    "모바일클릭수": st.column_config.NumberColumn(format="%.1f"),
    "PC클릭률": st.column_config.NumberColumn(format="%.2f%%"),
    "모바일클릭률": st.column_config.NumberColumn(format="%.2f%%"),
    "광고수": st.column_config.NumberColumn(format="%.1f"),
}


def render_keyword_filter(key_prefix: str) -> tuple:
    """공통 키워드 필터 UI. (텍스트, 경쟁도, 최소검색량, 최소클릭수) 반환"""
    with st.expander("필터 설정", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            text_filter = st.text_input(
                "키워드 검색",
                placeholder="포함 텍스트",
                key=f"{key_prefix}_text",
            )
        with c2:
            comp_filter = st.selectbox(
                "경쟁도",
                ["전체", "높음", "중간", "낮음"],
                key=f"{key_prefix}_comp",
            )
        with c3:
            min_total = st.number_input(
                "최소 검색량(합계)",
                value=0, min_value=0, step=100,
                key=f"{key_prefix}_min_total",
            )
        with c4:
            min_clicks = st.number_input(
                "최소 모바일클릭수",
                value=0.0, min_value=0.0, step=1.0,
                key=f"{key_prefix}_min_clicks",
            )

        def _reset():
            st.session_state[f"{key_prefix}_text"] = ""
            st.session_state[f"{key_prefix}_comp"] = "전체"
            st.session_state[f"{key_prefix}_min_total"] = 0
            st.session_state[f"{key_prefix}_min_clicks"] = 0.0

        st.button("필터 초기화", key=f"{key_prefix}_reset", on_click=_reset)

    return text_filter, comp_filter, min_total, min_clicks
