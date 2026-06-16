from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # 引入 CORS 中介軟體
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
import uvicorn
import traceback
from contextlib import asynccontextmanager
from sqlalchemy import text # 👈 【新增】用於發送極輕量的測試 SQL

# 引入官方正確的 MCP 客戶端與大腦建構工廠
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.agent.graph import make_agent_app
from src.core.config.settings import settings # 引入全域設定
from src.db.session import AsyncSessionLocal  # 引入資料庫 Session

# 宣告全域的 Runtime 實例變數
agent_app = None
mcp_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    2026 標準維運規範：管理 API 服務的非同步生命週期，確保連線通道與主迴圈共生。
    """
    global agent_app, mcp_client
    print("🔄 [Lifespan] 正在與 FastAPI 共用事件迴圈初始化基礎設施...")
    
    try:
        # 1. 敲門測試：確保 PostgreSQL 資料庫活著
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("✅ [Lifespan] PostgreSQL 資料庫連線測試成功！")

        # 2. 使用 settings 動態讀取 MCP 網址，徹底消除 Hardcode
        mcp_client = MultiServerMCPClient({
            "itops_tools": {
                "url": settings.MCP_SERVER_URL,
                "transport": "sse"
            }
        })
        
        # 3. 非同步獲取工具清單，此時網路 Session 會在同一個迴圈中保持長連線活躍
        mcp_tools = await mcp_client.get_tools()
        print(f"✅ [Lifespan] 成功於運作期迴圈中動態載入 {len(mcp_tools)} 把 MCP 工具！")
        
        # 4. 將工具注入工廠，完成狀態機實例化
        agent_app = make_agent_app(mcp_tools)
        print("🚀 [Lifespan] LangGraph Agent 狀態機編譯完畢，微服務準備就緒。")
        
        yield
        
    except Exception as e:
        print("❌ [Lifespan Critical Error] 初始化階段遭遇崩潰:")
        traceback.print_exc()
        raise e
    finally:
        # 5. 當伺服器關閉時，優雅斷開與 8001 端的通訊
        if mcp_client:
            print("🛑 [Lifespan] 正在安全釋放 MCP 遠端微服務連線通道...")
            if hasattr(mcp_client, "close"):
                await mcp_client.close()

# 初始化 FastAPI 並掛載生命週期管理器
app = FastAPI(
    title="ITOps AI Agent API",
    description="企業級 IT 維運自動化核心 API (Lifespan 最佳化解耦版)",
    version="1.0.0",
    lifespan=lifespan
)

# 掛載 CORS 防線，允許 Next.js 前端順利連線
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # POC 階段允許所有來源，正式上線應改為 Next.js 的網域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    thread_id: str
    message: str

@app.post("/api/v1/chat")
async def chat_endpoint(request: ChatRequest):
    global agent_app
    if agent_app is None:
        raise HTTPException(status_code=503, detail="Agent 服務尚未初始化完成，請稍後再試。")
        
    try:
        # 設定對話 Session ID
        config = {"configurable": {"thread_id": request.thread_id}}
        input_message = HumanMessage(content=request.message)
        
        # 呼叫 Agent 狀態機
        result = await agent_app.ainvoke({"messages": [input_message]}, config)
        raw_content = result["messages"][-1].content
        if isinstance(raw_content, list) and len(raw_content) > 0 and isinstance(raw_content[0], dict):
            final_response = raw_content[0].get("text", str(raw_content))
        else:
            final_response = raw_content
        
        return {
            "status": "success",
            "thread_id": request.thread_id,
            "response": final_response
        }
        
    except Exception as e:
        print("❌ [API 運作期異常] 攔截到未處理錯誤:")
        traceback.print_exc() # 強制噴出詳細 Traceback 防止 log 被遮蔽
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)