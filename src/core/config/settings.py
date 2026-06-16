from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 核心應用設定
    APP_NAME: str = "Enterprise AI Agent Harness"
    APP_ENV: str = "development"
    API_V1_STR: str = "/v1"
    SECRET_KEY: str

    # 數據庫連線設定
    DATABASE_URL: str

    # AI 模型金鑰
    GOOGLE_API_KEY: str

    # Agent_ID
    AGENT_ID: str = "ITOps-Agent-POC-01"

    # Pydantic Settings 設定，告訴它去哪裡找 .env
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        case_sensitive=True,
        extra="ignore"  # 忽略 .env 中有寫，但這裡沒定義的變數 (如 LANGFUSE 等)
    )

# 實例化 settings 物件，供全域匯入使用
settings = Settings()