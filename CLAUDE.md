# 네이버 키워드 분석 크롤링 도구

## 프로젝트 개요
네이버 검색 결과의 스마트블록을 분석하여 마케팅 키워드 전략을 수립하는 도구.
Playwright로 네이버를 크롤링하고, 키워드별 스마트블록(블로그/카페/인플루언서/지식인)을 파싱하여
카페 상위노출용/블로그 체험단용 키워드를 분류한다.

## 기술 스택
- Python 3.11 + Streamlit (UI)
- Playwright (Chromium, 시크릿 모드, Headed/Headless)
- BeautifulSoup4 (HTML 파싱)
- openpyxl (Excel 출력)
- 네이버 검색광고 API (검색량 조회)

## 실행 방법
```bash
# 로컬 실행 (Headed 브라우저 지원)
pip install -r requirements.txt
playwright install chromium
streamlit run app.py

# Docker 실행 (Headless 전용)
docker-compose up -d
```
포트: 8502

## 핵심 파일 구조
- `app.py` - Streamlit 메인 UI (6페이지)
- `crawler.py` - Playwright 네이버 크롤러 (차단 방지 내장)
- `parser.py` - 스마트블록 HTML 파서 (다중 셀렉터 폴백)
- `keyword_api.py` - 네이버 검색광고 API 클라이언트
- `classifier.py` - 카페/블로그 키워드 분류
- `excel_manager.py` - Excel 4시트 리포트 생성
- `models.py` - 공유 데이터 클래스
- `config.py` - 설정 관리 + 셀렉터 설정

## 네이버 HTML 구조 변경 대응
파서가 작동하지 않을 때:
1. `config.py`의 `BLOCK_SELECTORS` 딕셔너리 수정
2. `BLOCK_NAME_MAP` 딕셔너리에 새 블록 이름 추가
3. `parser.py`의 `NaverSearchParser(debug=True)`로 디버그 로그 확인

## 환경변수 (.env)
```
NAVER_CUSTOMER_ID=...
NAVER_API_KEY=...
NAVER_SECRET_KEY=...
```
