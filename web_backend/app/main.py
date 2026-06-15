from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .settings import settings
from .routes import router


app = FastAPI(title='ProTires Web Backend', version='1.0.0')

origins = [x.strip() for x in settings.allowed_origins.split(',') if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(router, prefix='/api')


@app.get('/health')
def health() -> dict:
    return {'status': 'ok'}
