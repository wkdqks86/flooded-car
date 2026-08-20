# flooded-car

금융위원회·보험개발원 공공데이터로 자동차 침수 이력을 조회하는 Streamlit 앱입니다.

## 실행

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
