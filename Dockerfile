FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 합성 비용 데이터를 빌드 시점에 생성한다 — .dockerignore가 로컬 data/costs.db를
# 빌드 컨텍스트에서 제외하므로(자격증명이 든 .env와 같은 이유로 이미지에 아무거나
# 딸려 들어가지 않게 하려는 것), 여기서 명시적으로 만들어야 한다. 시드가 고정돼
# 있어 매번 같은 데이터가 나온다(scripts/generate_data.py 참고).
RUN python scripts/generate_data.py

EXPOSE 8000

# AWS 자격증명은 이미지에 굽지 않는다 — `docker run --env-file .env ...`처럼
# 런타임에 주입해야 한다(README.md 실행 방법 참고).
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
