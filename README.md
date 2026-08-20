# flooded-car

금융위원회·보험개발원 공공데이터로 자동차 침수 이력을 조회하는 Streamlit 앱입니다.

## 로컬 실행

```powershell
uv sync
copy .env.example .env
```

`.env`에 공공데이터포털 인증키를 넣은 뒤:

```powershell
uv run streamlit run streamlit_app.py
```

```
DATA_GO_KR_SERVICE_KEY=발급받은_인증키
```

인증키는 저장소에 올리지 않습니다.

## Vercel 배포

이 앱은 Streamlit 서버라서 Vercel Python Function 진입점(`app.py` 등)으로는 실행되지 않습니다. `Dockerfile.vercel`로 컨테이너 배포합니다.

1. Vercel 프로젝트 **Environment Variables**에 `DATA_GO_KR_SERVICE_KEY`를 추가합니다.
2. GitHub `main`에 푸시하면 다시 빌드됩니다.

Container Images 권한이 없거나 Streamlit WebSocket이 끊기면 [Streamlit Community Cloud](https://share.streamlit.io) 배포를 권장합니다.
