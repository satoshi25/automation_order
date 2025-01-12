FROM python:3.11

# Chrome 설치
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable

# ChromeDriver 설치
RUN CHROME_DRIVER_VERSION=$(curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE) \
    && wget -N https://chromedriver.storage.googleapis.com/$CHROME_DRIVER_VERSION/chromedriver_linux64.zip \
    && unzip chromedriver_linux64.zip \
    && chmod +x chromedriver \
    && mv chromedriver /usr/local/bin/

WORKDIR /app
COPY . /app/

RUN mkdir -p /app/temp && \
    chmod 777 /app/temp

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]