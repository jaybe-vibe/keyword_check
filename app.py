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
import pandas as pd
import threading
import traceback
import time
import sys
import asyncio
from datetime import datetime
from pathlib import Path

from config import PROJECT_ROOT, load_config, save_config, get_naver_ads_credentials
from models import KeywordResult, BlockType, EXCLUDED_BLOCKS, PRIORITY_BLOCKS
from keyword_api import NaverAdsAPIClient
from crawler import NaverCrawler
from parser import NaverSearchParser
from classifier import (
    classify_all, get_keywords_by_type, analyze_keyword,
    get_top10_items, get_content_type, is_recent, TARGET_TYPES,
)
from excel_manager import ExcelReportGenerator


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
# 유틸리티 함수
# ============================================================
def _normalize_keyword(kw: str) -> str:
    """키워드 정규화: 공백 제거"""
    return kw.replace(" ", "").strip()


def _is_duplicate_keyword(kw: str, existing: list[str]) -> bool:
    """공백 제거 기준 중복 확인"""
    normalized = _normalize_keyword(kw)
    for existing_kw in existing:
        if _normalize_keyword(existing_kw) == normalized:
            return True
    return False


def _add_keywords(raw_keywords: list[str]) -> tuple[list[str], list[str]]:
    """키워드 추가. 공백 제거 + 중복 방지. (추가된 목록, 중복 목록) 반환"""
    added = []
    duplicates = []
    for kw in raw_keywords:
        normalized = _normalize_keyword(kw)
        if not normalized:
            continue
        if _is_duplicate_keyword(normalized, st.session_state.keywords):
            duplicates.append(kw)
        else:
            st.session_state.keywords.append(normalized)
            added.append(normalized)
    return added, duplicates


# ============================================================
# 크롤링 백그라운드 스레드 함수 (페이지 로직보다 먼저 정의)
# ============================================================
def _run_crawl_thread(keywords: list[str], crawler_config: dict,
                      shared: dict, results_dict: dict):
    """백그라운드에서 크롤링 실행 (threading.Thread 대상).

    Args:
        shared: 스레드↔메인 통신용 일반 dict (st.session_state 대신)
        results_dict: 키워드별 결과를 저장할 dict 참조
    """

    # Windows 수정: Tornado가 SelectorEventLoopPolicy를 전역 설정하지만,
    # Playwright는 subprocess 생성을 위해 ProactorEventLoop이 필요함
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    def on_status(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        shared["log"].append(f"[{timestamp}] {msg}")

    crawler = NaverCrawler(
        headed=crawler_config.get("headed", True),
        min_delay=crawler_config.get("min_delay", 3.0),
        max_delay=crawler_config.get("max_delay", 8.0),
        context_rotation_interval=crawler_config.get("context_rotation_interval", 12),
        on_status=on_status,
    )
    parser = NaverSearchParser(debug=True)

    try:
        crawler.start()

        for i, keyword in enumerate(keywords):
            if shared["stop_signal"]:
                on_status("크롤링 중지됨 (사용자 요청)")
                break

            while shared["pause_signal"]:
                time.sleep(0.5)
                if shared["stop_signal"]:
                    break

            if shared["stop_signal"]:
                break

            shared["current"] = keyword
            on_status(f"'{keyword}' 검색 시작")

            raw = crawler.search(keyword)

            if keyword not in results_dict:
                results_dict[keyword] = KeywordResult(keyword=keyword)

            result = results_dict[keyword]

            if raw["success"]:
                # 디버그 HTML 저장 (향후 파싱 문제 분석용)
                try:
                    debug_dir = Path("data/debug_html")
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    safe_name = keyword.replace("/", "_").replace("\\", "_")
                    with open(debug_dir / f"{safe_name}.html", "w", encoding="utf-8") as f:
                        f.write(raw["html"])
                except Exception:
                    pass

                parsed = parser.parse(raw["html"])
                result.smart_blocks = parsed["blocks"]
                result.related_keywords = parsed["related_keywords"]
                result.crawled_at = datetime.now()
                result.error = ""

                block_names = [b.block_name for b in parsed["blocks"]]
                on_status(f"'{keyword}' 완료: 블록 {len(block_names)}개 [{', '.join(block_names)}]")

                # 디버그 로그 출력
                if parsed.get("debug_log"):
                    for log_line in parsed["debug_log"]:
                        on_status(f"  [파서] {log_line}")
            else:
                result.error = raw["error"]
                result.crawled_at = datetime.now()
                on_status(f"'{keyword}' 오류: {raw['error']}")

                if raw.get("blocked"):
                    shared["pause_signal"] = True
                    shared["status"] = "paused"
                    on_status("차단 감지 - 크롤링 일시정지됨. 재개 버튼을 눌러주세요.")

            shared["completed"] = i + 1
            shared["progress"] = (i + 1) / len(keywords)

    except Exception as e:
        tb = traceback.format_exc()
        on_status(f"크롤링 오류: {type(e).__name__}: {e}")
        on_status(f"상세 traceback:\n{tb}")
        shared["status"] = "error"
    finally:
        crawler.stop()
        if shared["status"] != "error" and not shared["stop_signal"]:
            shared["status"] = "completed"
        shared["current"] = ""


# ============================================================
# 세션 상태 초기화
# ============================================================
def init_session_state():
    defaults = {
        "config": load_config(),
        "keywords": [],
        "results": {},
        # 크롤링 스레드 통신용 일반 dict (st.session_state 프록시가 아님)
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
with st.sidebar:
    st.title("🔍 키워드 분석")
    st.caption("네이버 검색결과 스마트블록 분석 도구")
    st.divider()

    page = st.radio(
        "메뉴",
        [
            "📋 키워드 관리",
            "🌐 네이버 크롤링",
            "📊 분석 결과",
            "🏷️ 키워드 분류",
            "📥 Excel 내보내기",
            "⚙️ 설정",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    kw_count = len(st.session_state.keywords)
    result_count = sum(
        1 for r in st.session_state.results.values()
        if isinstance(r, KeywordResult) and r.crawled_at
    )
    st.caption(f"키워드: {kw_count}개 | 분석완료: {result_count}개")

    crawl_shared = st.session_state.crawl_shared
    if crawl_shared["status"] == "running":
        st.info(f"크롤링 중: {crawl_shared['current']}")
    elif crawl_shared["status"] == "paused":
        st.warning("크롤링 일시정지")


# ============================================================
# 페이지 1: 키워드 관리
# ============================================================
if page == "📋 키워드 관리":
    st.header("📋 키워드 관리")

    # --- 키워드 입력 ---
    tab1, tab2 = st.tabs(["직접 입력", "파일 업로드"])

    with tab1:
        kw_input = st.text_area(
            "키워드 입력 (줄바꿈 또는 쉼표로 구분)",
            height=150,
            placeholder="임산부유산균\n임산부효소\n다이어트효소...",
        )
        if st.button("➕ 키워드 추가", key="add_kw"):
            if kw_input.strip():
                raw_kws = [line.strip() for line in kw_input.replace(",", "\n").split("\n")]
                added, duplicates = _add_keywords(raw_kws)
                if added:
                    st.success(f"{len(added)}개 키워드 추가됨 (공백 자동 제거)")
                if duplicates:
                    st.warning(f"중복 제외: {', '.join(duplicates)}")
                if not added and not duplicates:
                    st.warning("추가할 키워드가 없습니다")
                st.rerun()

    with tab2:
        uploaded = st.file_uploader(
            "텍스트 파일 업로드 (.txt, .csv)",
            type=["txt", "csv"],
        )
        if uploaded:
            content = uploaded.read().decode("utf-8")
            raw_kws = [line.strip() for line in content.replace(",", "\n").split("\n")]
            added, duplicates = _add_keywords(raw_kws)
            if added:
                st.success(f"{len(added)}개 키워드 업로드됨 (공백 자동 제거)")
            if duplicates:
                st.warning(f"중복 제외 {len(duplicates)}개")
            st.rerun()

    # --- 현재 키워드 목록 ---
    st.divider()
    st.subheader(f"현재 키워드 목록 ({len(st.session_state.keywords)}개)")

    if st.session_state.keywords:
        # 복합 필터
        with st.expander("필터 설정", expanded=False):
            fc1, fc2, fc3, fc4 = st.columns(4)
            with fc1:
                kw_filter = st.text_input(
                    "키워드 검색",
                    placeholder="포함 텍스트",
                    key="kw_list_filter",
                )
            with fc2:
                comp_options = ["전체", "높음", "중간", "낮음"]
                comp_filter = st.selectbox(
                    "경쟁도", comp_options, key="kw_comp_filter",
                )
            with fc3:
                min_total = st.number_input(
                    "최소 검색량(합계)", value=0, min_value=0, step=100,
                    key="kw_min_total",
                )
            with fc4:
                min_clicks = st.number_input(
                    "최소 모바일클릭수", value=0.0, min_value=0.0, step=1.0,
                    key="kw_min_clicks",
                )
            def _reset_kw_filters():
                st.session_state.kw_list_filter = ""
                st.session_state.kw_comp_filter = "전체"
                st.session_state.kw_min_total = 0
                st.session_state.kw_min_clicks = 0.0

            st.button("필터 초기화", key="kw_filter_reset", on_click=_reset_kw_filters)

        st.caption("열 헤더를 클릭하면 숫자 기준으로 정렬됩니다.")

        # 키워드 테이블 데이터 수집 (숫자 그대로 유지)
        kw_data = []
        for kw in st.session_state.keywords:
            if kw_filter and kw_filter not in kw:
                continue
            result = st.session_state.results.get(kw)
            if isinstance(result, KeywordResult):
                if comp_filter != "전체" and result.competition != comp_filter:
                    continue
                if result.search_volume_total < min_total:
                    continue
                if result.avg_mobile_clicks < min_clicks:
                    continue
                kw_data.append({
                    "키워드": kw,
                    "PC": result.search_volume_pc,
                    "모바일": result.search_volume_mobile,
                    "합계": result.search_volume_total,
                    "경쟁도": result.competition,
                    "PC클릭수": result.avg_pc_clicks,
                    "모바일클릭수": result.avg_mobile_clicks,
                    "PC클릭률": result.avg_pc_ctr,
                    "모바일클릭률": result.avg_mobile_ctr,
                    "광고수": result.avg_ad_count,
                    "분류": result.classification,
                    "크롤링": "O" if result.crawled_at else "",
                })
            else:
                if comp_filter != "전체":
                    continue
                if min_total > 0 or min_clicks > 0:
                    continue
                kw_data.append({
                    "키워드": kw,
                    "PC": 0, "모바일": 0, "합계": 0,
                    "경쟁도": "",
                    "PC클릭수": 0.0, "모바일클릭수": 0.0,
                    "PC클릭률": 0.0, "모바일클릭률": 0.0,
                    "광고수": 0.0,
                    "분류": "", "크롤링": "",
                })

        df = pd.DataFrame(kw_data)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "PC": st.column_config.NumberColumn(format="%d"),
                "모바일": st.column_config.NumberColumn(format="%d"),
                "합계": st.column_config.NumberColumn(format="%d"),
                "PC클릭수": st.column_config.NumberColumn(format="%.1f"),
                "모바일클릭수": st.column_config.NumberColumn(format="%.1f"),
                "PC클릭률": st.column_config.NumberColumn(format="%.2f%%"),
                "모바일클릭률": st.column_config.NumberColumn(format="%.2f%%"),
                "광고수": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption(f"필터 결과: {len(kw_data)}개 / 전체 {len(st.session_state.keywords)}개")

        # 키워드 삭제
        col1, col2 = st.columns(2)
        with col1:
            kw_to_delete = st.multiselect(
                "삭제할 키워드 선택",
                st.session_state.keywords,
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ 선택 키워드 삭제") and kw_to_delete:
                for kw in kw_to_delete:
                    st.session_state.keywords.remove(kw)
                    st.session_state.results.pop(kw, None)
                st.success(f"{len(kw_to_delete)}개 키워드 삭제됨")
                st.rerun()

        if st.button("🗑️ 전체 키워드 초기화", type="secondary"):
            st.session_state.keywords = []
            st.session_state.results = {}
            st.session_state.classified = False
            st.session_state.api_related_keywords = {}
            st.rerun()
    else:
        st.info("키워드를 입력해주세요.")

    # --- 검색량 조회 ---
    st.divider()
    st.subheader("🔍 검색량 조회 (네이버 검색광고 API)")

    if st.button("검색량 조회", type="primary", disabled=not st.session_state.keywords):
        creds = get_naver_ads_credentials()
        if not all(creds):
            st.error("네이버 검색광고 API 키가 설정되지 않았습니다. ⚙️ 설정 페이지에서 입력해주세요.")
        else:
            client = NaverAdsAPIClient(*creds)
            with st.spinner("검색량 조회 중..."):
                volumes = client.get_volumes_batched(st.session_state.keywords)

            for kw in st.session_state.keywords:
                if kw not in st.session_state.results:
                    st.session_state.results[kw] = KeywordResult(keyword=kw)

                vol = volumes.get(kw, {})
                result = st.session_state.results[kw]
                result.search_volume_pc = vol.get("pc", 0)
                result.search_volume_mobile = vol.get("mobile", 0)
                result.search_volume_total = vol.get("total", 0)
                result.competition = vol.get("competition", "")
                result.avg_pc_clicks = vol.get("avg_pc_clicks", 0.0)
                result.avg_mobile_clicks = vol.get("avg_mobile_clicks", 0.0)
                result.avg_pc_ctr = vol.get("avg_pc_ctr", 0.0)
                result.avg_mobile_ctr = vol.get("avg_mobile_ctr", 0.0)
                result.avg_ad_count = vol.get("avg_ad_count", 0.0)

            st.session_state.volumes_loaded = True
            st.success(f"{len(volumes)}개 키워드 검색량 조회 완료")
            st.rerun()

    # --- 연관키워드 조회 ---
    st.divider()
    st.subheader("🔗 연관키워드 조회 (네이버 검색광고 API)")
    st.caption("키워드를 선택하면 네이버 키워드 도구의 연관키워드를 조회하고, 원하는 키워드를 바로 추가할 수 있습니다.")

    if st.session_state.keywords:
        selected_for_related = st.selectbox(
            "연관키워드를 조회할 키워드",
            st.session_state.keywords,
            key="related_kw_select",
        )

        if st.button("🔗 연관키워드 조회", key="fetch_related"):
            creds = get_naver_ads_credentials()
            if not all(creds):
                st.error("API 키가 설정되지 않았습니다.")
            else:
                client = NaverAdsAPIClient(*creds)
                with st.spinner(f"'{selected_for_related}' 연관키워드 조회 중..."):
                    related = client.get_related_keywords(selected_for_related)
                st.session_state.api_related_keywords[selected_for_related] = related
                st.success(f"연관키워드 {len(related)}개 조회됨")
                st.rerun()

        # 연관키워드 결과 표시
        if selected_for_related in st.session_state.api_related_keywords:
            related_list = st.session_state.api_related_keywords[selected_for_related]

            if related_list:
                st.write(f"**'{selected_for_related}' 연관키워드 ({len(related_list)}개)**")

                # 복합 필터
                with st.expander("필터 설정", expanded=False):
                    rc1, rc2, rc3, rc4 = st.columns(4)
                    with rc1:
                        rel_filter = st.text_input(
                            "키워드 검색",
                            placeholder="포함 텍스트",
                            key="rel_kw_filter",
                        )
                    with rc2:
                        rel_comp_options = ["전체", "높음", "중간", "낮음"]
                        rel_comp_filter = st.selectbox(
                            "경쟁도", rel_comp_options, key="rel_comp_filter",
                        )
                    with rc3:
                        rel_min_total = st.number_input(
                            "최소 검색량(합계)", value=0, min_value=0, step=100,
                            key="rel_min_total",
                        )
                    with rc4:
                        rel_min_clicks = st.number_input(
                            "최소 모바일클릭수", value=0.0, min_value=0.0, step=1.0,
                            key="rel_min_clicks",
                        )
                    def _reset_rel_filters():
                        st.session_state.rel_kw_filter = ""
                        st.session_state.rel_comp_filter = "전체"
                        st.session_state.rel_min_total = 0
                        st.session_state.rel_min_clicks = 0.0

                    st.button("필터 초기화", key="rel_filter_reset", on_click=_reset_rel_filters)

                st.caption("체크박스로 추가할 키워드를 선택하세요.")

                # 테이블 데이터 생성 (숫자 그대로 유지)
                rel_data = []
                for rk in related_list:
                    if rel_filter and rel_filter not in rk["keyword"]:
                        continue
                    if rel_comp_filter != "전체" and rk["competition"] != rel_comp_filter:
                        continue
                    if rk["total"] < rel_min_total:
                        continue
                    if rk["avg_mobile_clicks"] < rel_min_clicks:
                        continue
                    already_in = _is_duplicate_keyword(rk["keyword"], st.session_state.keywords)
                    rel_data.append({
                        "추가": already_in,
                        "키워드": rk["keyword"],
                        "PC": rk["pc"],
                        "모바일": rk["mobile"],
                        "합계": rk["total"],
                        "경쟁도": rk["competition"],
                        "PC클릭수": rk["avg_pc_clicks"],
                        "모바일클릭수": rk["avg_mobile_clicks"],
                        "PC클릭률": rk["avg_pc_ctr"],
                        "모바일클릭률": rk["avg_mobile_ctr"],
                        "광고수": rk["avg_ad_count"],
                    })

                st.caption(f"필터 결과: {len(rel_data)}개 / 전체 {len(related_list)}개")

                if rel_data:
                    rel_df = pd.DataFrame(rel_data)

                    edited_df = st.data_editor(
                        rel_df,
                        use_container_width=True,
                        hide_index=True,
                        disabled=["키워드", "PC", "모바일", "합계", "경쟁도",
                                  "PC클릭수", "모바일클릭수", "PC클릭률", "모바일클릭률", "광고수"],
                        column_config={
                            "추가": st.column_config.CheckboxColumn("추가", default=False),
                            "PC": st.column_config.NumberColumn(format="%d"),
                            "모바일": st.column_config.NumberColumn(format="%d"),
                            "합계": st.column_config.NumberColumn(format="%d"),
                            "PC클릭수": st.column_config.NumberColumn(format="%.1f"),
                            "모바일클릭수": st.column_config.NumberColumn(format="%.1f"),
                            "PC클릭률": st.column_config.NumberColumn(format="%.2f%%"),
                            "모바일클릭률": st.column_config.NumberColumn(format="%.2f%%"),
                            "광고수": st.column_config.NumberColumn(format="%.1f"),
                        },
                        key="rel_kw_editor",
                    )

                    # 선택된 키워드 추가 버튼
                    col_btn1, col_btn2 = st.columns([1, 1])
                    with col_btn1:
                        if st.button("선택 키워드 추가", key="add_selected_related"):
                            selected_kws = edited_df[edited_df["추가"] == True]["키워드"].tolist()
                            new_kws = [kw for kw in selected_kws
                                       if not _is_duplicate_keyword(kw, st.session_state.keywords)]
                            if new_kws:
                                added, _ = _add_keywords(new_kws)
                                st.success(f"{len(added)}개 키워드 추가됨")
                                st.rerun()
                            else:
                                st.info("추가할 새 키워드가 없습니다")
                    with col_btn2:
                        if st.button("전체 추가 (필터 결과)", key="add_all_related"):
                            raw_kws = [r["키워드"] for r in rel_data]
                            added, _ = _add_keywords(raw_kws)
                            if added:
                                st.success(f"{len(added)}개 연관키워드 추가됨")
                                st.rerun()
                            else:
                                st.info("이미 모두 등록된 키워드입니다")
            else:
                st.info("연관키워드가 없습니다.")


# ============================================================
# 페이지 2: 네이버 크롤링
# ============================================================
elif page == "🌐 네이버 크롤링":
    st.header("🌐 네이버 크롤링")

    if not st.session_state.keywords:
        st.warning("📋 키워드 관리 페이지에서 먼저 키워드를 입력해주세요.")
    else:
        st.info(f"분석 대상: {len(st.session_state.keywords)}개 키워드")

        config = st.session_state.config

        # 크롤링 옵션
        with st.expander("크롤링 옵션", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                min_delay = st.number_input(
                    "최소 딜레이(초)", value=float(config.get("min_delay", 3.0)),
                    min_value=1.0, max_value=30.0, step=0.5,
                )
            with col2:
                max_delay = st.number_input(
                    "최대 딜레이(초)", value=float(config.get("max_delay", 8.0)),
                    min_value=2.0, max_value=60.0, step=0.5,
                )
            with col3:
                rotation = st.number_input(
                    "컨텍스트 교체 간격", value=int(config.get("context_rotation_interval", 12)),
                    min_value=5, max_value=50, step=1,
                )
            headed = st.checkbox(
                "브라우저 화면 표시 (Headed 모드)",
                value=config.get("headed", True),
            )

        # shared dict 참조 (스레드와 공유하는 일반 dict)
        shared = st.session_state.crawl_shared

        # 크롤링 제어 버튼
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            start_disabled = shared["status"] in ("running", "paused")
            if st.button("크롤링 시작", type="primary", disabled=start_disabled):
                # shared dict 초기화
                shared["status"] = "running"
                shared["progress"] = 0.0
                shared["completed"] = 0
                shared["log"] = []
                shared["stop_signal"] = False
                shared["pause_signal"] = False
                shared["current"] = ""

                # 백그라운드 스레드로 크롤링 실행
                thread = threading.Thread(
                    target=_run_crawl_thread,
                    args=(
                        list(st.session_state.keywords),
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

        # 진행 상태 표시
        st.divider()

        if shared["status"] in ("running", "paused"):
            total = len(st.session_state.keywords)
            completed = shared["completed"]
            progress = completed / total if total > 0 else 0

            st.progress(progress, text=f"진행: {completed}/{total} ({progress*100:.0f}%)")

            if shared["current"]:
                st.write(f"현재 키워드: **{shared['current']}**")

            # 크롤링 로그 (진행 중에도 표시)
            if shared["log"]:
                with st.expander("크롤링 로그", expanded=True):
                    for log_entry in shared["log"][-30:]:
                        st.text(log_entry)

            # 자동 새로고침 (2초마다)
            time.sleep(2)
            st.rerun()

        elif shared["status"] == "completed":
            st.success("크롤링 완료!")
            completed = shared["completed"]
            total = len(st.session_state.keywords)
            errors = sum(
                1 for r in st.session_state.results.values()
                if isinstance(r, KeywordResult) and r.error
            )
            st.write(f"완료: {completed}/{total}개 | 오류: {errors}개")

        elif shared["status"] == "error":
            st.error("크롤링 오류 발생!")

        # 크롤링 로그 (완료/에러 상태에서도 표시, 에러 시 자동 펼침)
        if shared["status"] in ("completed", "error", "idle") and shared["log"]:
            log_expanded = shared["status"] == "error"
            with st.expander("크롤링 로그", expanded=log_expanded):
                for log_entry in shared["log"][-50:]:
                    st.text(log_entry)

        # 개별 키워드 결과 요약
        st.divider()
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
                    "연관키워드": len(result.related_keywords),
                    "오류": result.error or "-",
                })

        if crawled_data:
            st.dataframe(pd.DataFrame(crawled_data), use_container_width=True, hide_index=True)
        else:
            st.info("아직 크롤링된 키워드가 없습니다.")


# ============================================================
# 페이지 3: 분석 결과
# ============================================================
elif page == "📊 분석 결과":
    st.header("📊 분석 결과")

    crawled_results = {
        kw: r for kw, r in st.session_state.results.items()
        if isinstance(r, KeywordResult) and r.crawled_at
    }

    if not crawled_results:
        st.warning("🌐 네이버 크롤링을 먼저 실행해주세요.")
    else:
        st.success(f"분석된 키워드: {len(crawled_results)}개")

        # 분류 실행 (자동)
        analyses = classify_all(st.session_state.results)

        # --- 키워드별 상위 10위 유형 분석 ---
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
                "인플루언서": f"{tc['인플루언서']} ({trc['인플루언서']}추천)" if tc["인플루언서"] > 0 else "0",
                "지식인": str(tc["지식인"]),
                "추천유형": "/".join(analysis["recommended_types"]) if analysis["recommended_types"] else "-",
            }
            analysis_data.append(row)

        st.dataframe(pd.DataFrame(analysis_data), use_container_width=True, hide_index=True)

        # --- 키워드별 상세 결과 ---
        st.subheader("키워드별 상세 결과")
        selected_kw = st.selectbox(
            "키워드 선택",
            list(crawled_results.keys()),
        )

        if selected_kw:
            result = crawled_results[selected_kw]
            analysis = analyses.get(selected_kw, analyze_keyword(result))

            # 유형별 메트릭
            tc = analysis["type_counts"]
            trc = analysis["type_recent_counts"]
            icons = {"블로그": "📝", "카페": "☕", "인플루언서": "⭐", "지식인": "❓"}
            cols = st.columns(4)
            for col, ctype in zip(cols, TARGET_TYPES):
                if ctype == "지식인":
                    label = f"{tc[ctype]}개"
                else:
                    label = f"{tc[ctype]}개 (추천 {trc[ctype]})"
                col.metric(f"{icons[ctype]} {ctype}", label)

            recommended = analysis["recommended_types"]
            if recommended:
                st.info(f"추천유형: **{'/'.join(recommended)}**")

            # 상위 10위 콘텐츠 테이블
            top10 = get_top10_items(result)
            if top10:
                st.write("**상위 10위 콘텐츠**")
                detail_data = []
                for rank, item in enumerate(top10, 1):
                    ctype = get_content_type(item.url)
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
                    pd.DataFrame(detail_data),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "순위": st.column_config.NumberColumn(width="small"),
                    },
                )

            # 함께 많이 찾는 키워드
            if result.related_keywords:
                st.subheader("함께 많이 찾는 키워드")
                cols = st.columns(min(len(result.related_keywords), 4))
                for i, rk in enumerate(result.related_keywords):
                    with cols[i % len(cols)]:
                        already_in = _is_duplicate_keyword(rk, st.session_state.keywords)
                        if already_in:
                            st.write(f"✅ {rk}")
                        else:
                            if st.button(f"➕ {rk}", key=f"add_related_{selected_kw}_{i}"):
                                added, _ = _add_keywords([rk])
                                if added:
                                    st.success(f"'{added[0]}' 추가됨")
                                    st.rerun()


# ============================================================
# 페이지 4: 키워드 분류
# ============================================================
elif page == "🏷️ 키워드 분류":
    st.header("🏷️ 키워드 분류")
    st.caption(
        "블로그/카페/인플루언서: 상위 10위 내 3개 이상 & 3개월 이내 → 추천 | "
        "지식인: 상위 10위 내 2개 이상 → 추천 | "
        "동일 유형이 많을수록 우선순위 상승"
    )

    crawled_results = {
        kw: r for kw, r in st.session_state.results.items()
        if isinstance(r, KeywordResult) and r.crawled_at
    }

    if not crawled_results:
        st.warning("🌐 네이버 크롤링을 먼저 실행해주세요.")
    else:
        # 분류 자동 실행
        classify_all(st.session_state.results)
        by_type = get_keywords_by_type(st.session_state.results)

        icons = {"블로그": "📝", "카페": "☕", "인플루언서": "⭐", "지식인": "❓"}

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
                    pd.DataFrame(type_data),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "우선순위": st.column_config.NumberColumn(width="small"),
                        "총 검색량": st.column_config.NumberColumn(format="%d"),
                    },
                )
            else:
                st.info(f"{ctype} 추천 키워드 없음")

        # 전체 분류 요약 테이블
        st.divider()
        st.subheader("전체 분류 결과")
        class_data = []
        for kw in st.session_state.keywords:
            result = st.session_state.results.get(kw)
            if isinstance(result, KeywordResult) and result.crawled_at:
                analysis = analyze_keyword(result)
                tc = analysis["type_counts"]
                class_data.append({
                    "키워드": kw,
                    "추천유형": result.classification or "-",
                    "블로그": tc["블로그"],
                    "카페": tc["카페"],
                    "인플루언서": tc["인플루언서"],
                    "지식인": tc["지식인"],
                    "총 검색량": result.search_volume_total,
                })
        if class_data:
            st.dataframe(
                pd.DataFrame(class_data),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "총 검색량": st.column_config.NumberColumn(format="%d"),
                },
            )


# ============================================================
# 페이지 5: Excel 내보내기
# ============================================================
elif page == "📥 Excel 내보내기":
    st.header("📥 Excel 내보내기")

    crawled_count = sum(
        1 for r in st.session_state.results.values()
        if isinstance(r, KeywordResult) and r.crawled_at
    )

    if crawled_count == 0:
        st.warning("분석된 키워드가 없습니다. 먼저 크롤링을 실행해주세요.")
    else:
        st.info(f"내보내기 대상: {crawled_count}개 키워드")

        st.markdown("""
        **포함 시트:**
        1. **키워드 목록** - 키워드별 검색량, 클릭수, 클릭률, 경쟁도, 분류
        2. **상세 콘텐츠** - 키워드/블록별 개별 콘텐츠 (유형, 추천유형, 제목, URL, 출처, 날짜, 추천)
        3. **연관 키워드** - 원본 키워드 ↔ 함께 많이 찾는 연관검색어
        """)

        if st.button("📥 Excel 파일 생성", type="primary"):
            with st.spinner("Excel 파일 생성 중..."):
                generator = ExcelReportGenerator()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = PROJECT_ROOT / st.session_state.config.get("output_dir", "data")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / f"keyword_analysis_{timestamp}.xlsx")

                generator.generate(st.session_state.results, output_path)

            st.success(f"Excel 파일 생성 완료: {Path(output_path).name}")

            with open(output_path, "rb") as f:
                st.download_button(
                    "💾 다운로드",
                    data=f.read(),
                    file_name=Path(output_path).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


# ============================================================
# 페이지 6: 설정
# ============================================================
elif page == "⚙️ 설정":
    st.header("⚙️ 설정")

    config = st.session_state.config

    # 네이버 검색광고 API
    st.subheader("네이버 검색광고 API")
    st.caption("searchad.naver.com에서 무료 가입 후 API 키를 발급받으세요.")

    creds = get_naver_ads_credentials()
    has_creds = all(creds)

    if has_creds:
        st.success("✅ API 키가 설정되어 있습니다.")
    else:
        st.warning("⚠️ API 키가 설정되지 않았습니다.")

    st.code(
        "# .env 파일에 아래 내용을 추가하세요:\n"
        "NAVER_CUSTOMER_ID=your_customer_id\n"
        "NAVER_API_KEY=your_api_key\n"
        "NAVER_SECRET_KEY=your_secret_key",
        language="bash",
    )

    # 크롤링 설정
    st.divider()
    st.subheader("크롤링 설정")

    col1, col2 = st.columns(2)
    with col1:
        config["min_delay"] = st.number_input(
            "최소 딜레이(초)",
            value=float(config.get("min_delay", 3.0)),
            min_value=1.0, max_value=30.0, step=0.5,
        )
        config["max_delay"] = st.number_input(
            "최대 딜레이(초)",
            value=float(config.get("max_delay", 8.0)),
            min_value=2.0, max_value=60.0, step=0.5,
        )
    with col2:
        config["context_rotation_interval"] = st.number_input(
            "컨텍스트 교체 간격 (키워드 수)",
            value=int(config.get("context_rotation_interval", 12)),
            min_value=5, max_value=50, step=1,
        )
        config["headed"] = st.checkbox(
            "브라우저 화면 표시 (Headed 모드)",
            value=config.get("headed", True),
        )

    if st.button("💾 설정 저장"):
        save_config(config)
        st.session_state.config = config
        st.success("설정이 저장되었습니다.")
