from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=('.env', str(BACKEND_DIR / '.env')),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    backend_host: str = '0.0.0.0'
    backend_port: int = 18080

    car_number_api_url: str = ''
    tire_number_api_url: str = ''
    tire_analysis_api_url: str = ''

    upstream_timeout_sec: int = 120
    allowed_origins: str = 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080'

    # Shared project paths / integration
    project_root: str = str(PROJECT_ROOT_DEFAULT)
    users_dir: str = 'Users'
    atwork_dir: str = 'AtWork'
    car_number_file_path: str = 'dir_json/car_number.json'
    demo_img_dir: str = 'DEMO_img'

    # 1C upload
    base_url: str = ''
    base_test: str = ''
    admin_username: str = ''
    admin_password: str = ''
    log_upload_dir: str = 'log_upload'

    # S3 sync
    s3_sync_mode: str = 'on_demand'
    s3_sync_verbose: bool = False
    s3_prefix: str = 'AITyres/users/'
    s3_bucket_name: str = 'rgtelegram'
    aws_access_key_id: str = ''
    aws_secret_access_key: str = ''
    yc_endpoint_url: str = 'https://storage.yandexcloud.net'
    yc_region: str = 'ru-central1'


settings = Settings()
