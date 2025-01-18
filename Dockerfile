FROM python:3.11-slim

# 필요한 패키지 한번에 설치 (레이어 최소화)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    chromium-chromedriver \
    google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* # 캐시 정리

WORKDIR /app

# 먼저 requirements.txt만 복사하여 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 파일 복사
COPY . .

# 필요한 디렉토리 생성 및 권한 설정
RUN mkdir -p /root/.cache/selenium \
    && chmod -R 777 /root/.cache/selenium \
    && chmod 777 /app

CMD ["python", "main.py"]