"""페이지 1: 키워드 관리"""

import streamlit as st
import pandas as pd

from models import KeywordResult
from config import get_naver_ads_credentials
from keyword_api import NaverAdsAPIClient
from utils.keyword_utils import add_keywords, is_duplicate_keyword
from utils.ui_components import render_keyword_filter, VOLUME_COLUMN_CONFIG


def render():
    st.header("📋 키워드 관리")

    _render_keyword_input()

    st.divider()
    _render_keyword_list()

    st.divider()
    _render_volume_search()

    st.divider()
    _render_related_keywords()


def _render_keyword_input():
    """키워드 입력 (직접 입력 + 파일 업로드)"""
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
                added, duplicates = add_keywords(raw_kws)
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
            if uploaded.size > 1_000_000:  # 1MB 제한
                st.error("파일 크기가 1MB를 초과합니다.")
                return
            try:
                content = uploaded.read().decode("utf-8")
            except UnicodeDecodeError:
                try:
                    uploaded.seek(0)
                    content = uploaded.read().decode("euc-kr")
                except UnicodeDecodeError:
                    st.error("파일 인코딩을 인식할 수 없습니다. UTF-8 또는 EUC-KR 파일을 사용해주세요.")
                    return
            raw_kws = [line.strip() for line in content.replace(",", "\n").split("\n")]
            if len(raw_kws) > 5000:
                st.error("키워드 수가 5,000개를 초과합니다.")
                return
            added, duplicates = add_keywords(raw_kws)
            if added:
                st.success(f"{len(added)}개 키워드 업로드됨 (공백 자동 제거)")
            if duplicates:
                st.warning(f"중복 제외 {len(duplicates)}개")
            st.rerun()


def _render_keyword_list():
    """현재 키워드 목록"""
    st.subheader(f"현재 키워드 목록 ({len(st.session_state.keywords)}개)")

    if not st.session_state.keywords:
        st.info("키워드를 입력해주세요.")
        return

    kw_filter, comp_filter, min_total, min_clicks = render_keyword_filter("kw_list")

    st.caption("열 헤더를 클릭하면 숫자 기준으로 정렬됩니다.")

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
                "선택": False,
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
                "선택": False,
                "키워드": kw,
                "PC": 0, "모바일": 0, "합계": 0,
                "경쟁도": "",
                "PC클릭수": 0.0, "모바일클릭수": 0.0,
                "PC클릭률": 0.0, "모바일클릭률": 0.0,
                "광고수": 0.0,
                "분류": "", "크롤링": "",
            })

    # 필터된 키워드 목록을 세션에 저장 (크롤링 페이지에서 사용)
    st.session_state.filtered_keywords = [d["키워드"] for d in kw_data]

    df = pd.DataFrame(kw_data)
    if df.empty:
        st.info("필터 조건에 맞는 키워드가 없습니다.")
        return

    edited_df = st.data_editor(
        df, use_container_width=True, hide_index=True,
        disabled=[c for c in df.columns if c != "선택"],
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", default=False),
            **VOLUME_COLUMN_CONFIG,
        },
        key="kw_list_editor",
    )
    st.caption(f"필터 결과: {len(kw_data)}개 / 전체 {len(st.session_state.keywords)}개")

    # 키워드 삭제 (체크박스로 선택된 키워드)
    selected_kws = edited_df[edited_df["선택"]]["키워드"].tolist()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 선택 키워드 삭제", disabled=not selected_kws):
            for kw in selected_kws:
                st.session_state.keywords.remove(kw)
                st.session_state.results.pop(kw, None)
            st.success(f"{len(selected_kws)}개 키워드 삭제됨")
            st.rerun()
    with col2:
        if st.button("🗑️ 전체 키워드 초기화", type="secondary"):
            st.session_state.keywords = []
            st.session_state.results = {}
            st.session_state.classified = False
            st.session_state.api_related_keywords = {}
            st.rerun()


def _render_volume_search():
    """검색량 조회"""
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


def _render_related_keywords():
    """연관키워드 조회"""
    st.subheader("🔗 연관키워드 조회 (네이버 검색광고 API)")
    st.caption("키워드를 선택하면 네이버 키워드 도구의 연관키워드를 조회하고, 원하는 키워드를 바로 추가할 수 있습니다.")

    if not st.session_state.keywords:
        return

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

    if selected_for_related not in st.session_state.api_related_keywords:
        return

    related_list = st.session_state.api_related_keywords[selected_for_related]
    if not related_list:
        st.info("연관키워드가 없습니다.")
        return

    st.write(f"**'{selected_for_related}' 연관키워드 ({len(related_list)}개)**")

    rel_filter, rel_comp_filter, rel_min_total, rel_min_clicks = render_keyword_filter("rel_kw")

    st.caption("체크박스로 추가할 키워드를 선택하세요.")

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
        already_in = is_duplicate_keyword(rk["keyword"], st.session_state.keywords)
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

    if not rel_data:
        return

    rel_df = pd.DataFrame(rel_data)
    edited_df = st.data_editor(
        rel_df, use_container_width=True, hide_index=True,
        disabled=["키워드", "PC", "모바일", "합계", "경쟁도",
                  "PC클릭수", "모바일클릭수", "PC클릭률", "모바일클릭률", "광고수"],
        column_config={
            "추가": st.column_config.CheckboxColumn("추가", default=False),
            **VOLUME_COLUMN_CONFIG,
        },
        key="rel_kw_editor",
    )

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        if st.button("선택 키워드 추가", key="add_selected_related"):
            selected_kws = edited_df[edited_df["추가"]]["키워드"].tolist()
            new_kws = [kw for kw in selected_kws
                       if not is_duplicate_keyword(kw, st.session_state.keywords)]
            if new_kws:
                added, _ = add_keywords(new_kws)
                st.success(f"{len(added)}개 키워드 추가됨")
                st.rerun()
            else:
                st.info("추가할 새 키워드가 없습니다")
    with col_btn2:
        if st.button("전체 추가 (필터 결과)", key="add_all_related"):
            raw_kws = [r["키워드"] for r in rel_data]
            added, _ = add_keywords(raw_kws)
            if added:
                st.success(f"{len(added)}개 연관키워드 추가됨")
                st.rerun()
            else:
                st.info("이미 모두 등록된 키워드입니다")
