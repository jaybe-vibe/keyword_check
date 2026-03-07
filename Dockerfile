FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 (한글 로케일 + Playwright 의존성)
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-nanum fonts-nanum-coding \
    && sed -i '/ko_KR.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=ko_KR.UTF-8
ENV LC_ALL=ko_KR.UTF-8

# Python 패키지
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium 설치
RUN playwright install chromium && playwright install-deps chromium

# 프로젝트 파일 복사
COPY . .

# Streamlit 설정
RUN mkdir -p /root/.streamlit
RUN printf '[server]\nheadless = true\nport = 8502\nenableCORS = false\nenableXsrfProtection = false\n\n[browser]\ngatherUsageStats = false\n' > /root/.streamlit/config.toml

EXPOSE 8502

CMD ["streamlit", "run", "app.py"]
