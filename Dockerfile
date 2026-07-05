# FreshRun API — 배포 이미지 (Fly.io 등 컨테이너 호스팅용)
# 로컬은 3.14로 개발하지만 배포는 3.13 안정 이미지에 고정 (pyproject: ^3.11).
FROM python:3.13-slim

WORKDIR /app

# 의존성 레이어 분리 — 코드만 바뀌면 캐시 재사용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# 배포 v1 = workers 1 (인메모리 가정·레이스 방어 전수 확인 기준 — 배포 설계 문서).
# 호스팅이 주입하는 $PORT에 0.0.0.0 바인드.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
