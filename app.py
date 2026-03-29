"""
네이버 키워드 분석 도구 - Streamlit 메인 UI

페이지:
1. 📋 키워드 관리 - 키워드 입력, 검색량 조회, 연관키워드
2. 🌐 네이버 크롤링 - 크롤링 실행/제어
3. 📊 분석 결과 - 스마트블록 분석
4. 🏷️ 키워드 분류 - 카페/블로그 분류
5. 📥 Excel 내보내기 - 리포트 다운로드
6. ⚙️ 설정 - API 키, 크롤링 파라미터
"""

import streamlit as st

from config import load_config
from models import KeywordResult
from pages import keyword_management, crawling, analysis, classification, export, settings


# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(
    page_title="네이버 키워드 분석",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 세션 상태 초기화
# ============================================================
def init_session_state():
    defaults = {
        "config": load_config(),
        "keywords": [],
        "results": {},
        "filtered_keywords": [],
        "crawl_shared": {
            "status": "idle",
            "progress": 0.0,
            "current": "",
            "completed": 0,
            "log": [],
            "stop_signal": False,
            "pause_signal": False,
        },
        "volumes_loaded": False,
        "classified": False,
        "api_related_keywords": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ============================================================
# 사이드바 네비게이션
# ============================================================
PAGE_MAP = {
    "📋 키워드 관리": keyword_management.render,
    "🌐 네이버 크롤링": crawling.render,
    "📊 분석 결과": analysis.render,
    "🏷️ 키워드 분류": classification.render,
    "📥 Excel 내보내기": export.render,
    "⚙️ 설정": settings.render,
}

st.markdown(
    "<style>[data-testid='stSidebarNav'] { display: none; }</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.title("🔍 키워드 분석")
    st.caption("네이버 검색결과 스마트블록 분석 도구")
    st.divider()

    page = st.radio("메뉴", list(PAGE_MAP.keys()), label_visibility="collapsed")

    st.divider()
    kw_count = len(st.session_state.keywords)
    result_count = sum(
        1 for r in st.session_state.results.values()
        if isinstance(r, KeywordResult) and r.crawled_at
    )

    crawl_shared = st.session_state.crawl_shared
    crawl_total = crawl_shared.get("total", kw_count)
    if crawl_shared["status"] in ("running", "paused") and crawl_total < kw_count:
        st.caption(f"키워드: {kw_count}개 (크롤링 대상: {crawl_total}개) | 분석완료: {result_count}개")
    else:
        st.caption(f"키워드: {kw_count}개 | 분석완료: {result_count}개")

    if crawl_shared["status"] == "running":
        st.info(f"크롤링 중: {crawl_shared['current']}")
    elif crawl_shared["status"] == "paused":
        st.warning("크롤링 일시정지")


# ============================================================
# 페이지 렌더링
# ============================================================
PAGE_MAP[page]()
