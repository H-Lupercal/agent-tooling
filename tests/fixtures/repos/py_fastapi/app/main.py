APP_NAME = "fixture-fastapi-app"


@app.get("/")
def read_root():
    return {"status": "ok"}
