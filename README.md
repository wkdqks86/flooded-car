# flooded-car

금융위원회·보험개발원 공공데이터로 자동차 침수 이력을 조회합니다.

## 로컬 실행

```powershell
uv sync --group local
copy .env.example .env
```

`.env`에 공공데이터포털 인증키를 넣은 뒤:

로컬 Streamlit은 한 번 `uv sync --group local` 후:

```powershell
uv run streamlit run streamlit_app.py
```

또는 Vercel과 같은 FastAPI 화면:

```powershell
uv run uvicorn app:app --reload
```

```
DATA_GO_KR_SERVICE_KEY=발급받은_인증키
```

인증키는 저장소에 올리지 않습니다.

## Vercel 배포

Streamlit은 Vercel Function에서 서버를 상시 띄울 수 없어, 배포는 FastAPI(`app.py`)를 사용합니다.

1. Vercel 프로젝트 **Environment Variables**에 `DATA_GO_KR_SERVICE_KEY`를 추가합니다.
2. GitHub `main`에 푸시하면 다시 빌드됩니다.
