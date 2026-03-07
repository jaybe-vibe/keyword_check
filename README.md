# 네이버 키워드 분석 크롤링 도구

네이버 검색 결과의 스마트블록을 분석하여 마케팅 키워드 전략을 수립하는 도구입니다.
Playwright로 네이버를 크롤링하고, 키워드별 스마트블록(블로그/카페/인플루언서/지식인)을 파싱하여 카페 상위노출용/블로그 체험단용 키워드를 자동 분류합니다.

## 주요 기능

- 네이버 검색광고 API를 통한 키워드 검색량 조회
- Playwright 기반 네이버 검색 결과 크롤링 (차단 방지 내장)
- 스마트블록 HTML 파싱 (다중 셀렉터 폴백)
- 카페/블로그 키워드 자동 분류
- Excel 4시트 리포트 생성

## 기술 스택

- Python 3.11 + Streamlit (UI)
- Playwright (Chromium, 시크릿 모드)
- BeautifulSoup4 (HTML 파싱)
- openpyxl (Excel 출력)
- 네이버 검색광고 API

## 실행 방법

### 로컬 실행

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

### Docker 실행

```bash
docker-compose up -d
```

포트: `8502`

## 환경변수

`.env` 파일을 프로젝트 루트에 생성합니다.

```
NAVER_CUSTOMER_ID=...
NAVER_API_KEY=...
NAVER_SECRET_KEY=...
```

## 프로젝트 구조

```
app.py           # Streamlit 메인 UI (6페이지)
crawler.py       # Playwright 네이버 크롤러
parser.py        # 스마트블록 HTML 파서
keyword_api.py   # 네이버 검색광고 API 클라이언트
classifier.py    # 카페/블로그 키워드 분류
excel_manager.py # Excel 리포트 생성
models.py        # 공유 데이터 클래스
config.py        # 설정 관리 + 셀렉터 설정
```

## UI 페이지

1. 키워드 관리 - 키워드 입력, 검색량 조회, 연관키워드
2. 네이버 크롤링 - 크롤링 실행/제어
3. 분석 결과 - 스마트블록 분석
4. 키워드 분류 - 카페/블로그 분류
5. Excel 내보내기 - 리포트 다운로드
6. 설정 - API 키, 크롤링 파라미터
