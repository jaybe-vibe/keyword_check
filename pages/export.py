"""페이지 5: Excel 내보내기"""

import streamlit as st
from datetime import datetime
from pathlib import Path

from models import KeywordResult
from config import PROJECT_ROOT
from excel_manager import ExcelReportGenerator


def render():
    st.header("📥 Excel 내보내기")

    crawled_count = sum(
        1 for r in st.session_state.results.values()
        if isinstance(r, KeywordResult) and r.crawled_at
    )

    if crawled_count == 0:
        st.warning("분석된 키워드가 없습니다. 먼저 크롤링을 실행해주세요.")
        return

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
