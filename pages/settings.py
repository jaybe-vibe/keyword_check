"""페이지 6: 설정"""

import streamlit as st
from config import get_naver_ads_credentials, save_config


def render():
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

    # 크롤링 설정 (임시 변수 패턴으로 직접 mutation 방지)
    st.divider()
    st.subheader("크롤링 설정")

    col1, col2 = st.columns(2)
    with col1:
        draft_min_delay = st.number_input(
            "최소 딜레이(초)",
            value=float(config.get("min_delay", 3.0)),
            min_value=1.0, max_value=30.0, step=0.5,
            key="settings_min_delay",
        )
        draft_max_delay = st.number_input(
            "최대 딜레이(초)",
            value=float(config.get("max_delay", 8.0)),
            min_value=2.0, max_value=60.0, step=0.5,
            key="settings_max_delay",
        )
    with col2:
        draft_rotation = st.number_input(
            "컨텍스트 교체 간격 (키워드 수)",
            value=int(config.get("context_rotation_interval", 12)),
            min_value=5, max_value=50, step=1,
            key="settings_rotation",
        )
        draft_headed = st.checkbox(
            "브라우저 화면 표시 (Headed 모드)",
            value=config.get("headed", False),
            key="settings_headed",
        )

    draft_min_related_volume = st.number_input(
        "연관키워드 최소 총검색량",
        value=int(config.get("min_related_volume", 1000)),
        min_value=0, max_value=100000, step=100,
        help="크롤링 후 연관키워드 중 총검색량이 이 값 미만인 키워드를 자동 제외합니다. 0이면 필터 없음.",
        key="settings_min_related_volume",
    )

    if st.button("💾 설정 저장"):
        updated_config = config.copy()
        updated_config["min_delay"] = draft_min_delay
        updated_config["max_delay"] = draft_max_delay
        updated_config["context_rotation_interval"] = draft_rotation
        updated_config["headed"] = draft_headed
        updated_config["min_related_volume"] = draft_min_related_volume
        save_config(updated_config)
        st.session_state.config = updated_config
        st.success("설정이 저장되었습니다.")
