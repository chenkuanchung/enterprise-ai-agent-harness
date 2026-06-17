from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
import uvicorn
import traceback
from contextlib import asynccontextmanager
from sqlalchemy import text 

from langchain_mcp_adapters.client import MultiServerMCPClient
from src.agent.graph import make_agent_app
from src.core.config.settings import settings
from src.db.session import AsyncSessionLocal 

# 👈 【企業級新增 1】引入 LangGraph Postgres 記憶體相關套件
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

# 宣告全域的 Runtime 實例變數
agent_app = None
mcp_client = None
langgraph_pool = None  # 👈 【企業級新增 2】記憶體連線池

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_app, mcp_client, langgraph_pool
    print("🔄 [Lifespan] 正在與 FastAPI 共用事件迴圈初始化基礎設施...")
    
    try:
        # 1. 敲門測試：確保 PostgreSQL 資料庫活著
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("✅ [Lifespan] PostgreSQL 資料庫連線測試成功！")

        # 2. 👈 【企業級新增 3】準備 LangGraph 專用的 Postgres Checkpointer
        # 將 sqlalchemy 的 postgresql+asyncpg:// 轉換為 psycopg 支援的 postgresql://
        sync_conn_str = settings.DATABASE_URL.replace("+asyncpg", "")
        langgraph_pool = AsyncConnectionPool(
            conninfo=sync_conn_str,
            max_size=20,
            kwargs={"autocommit": True},
            open=False                   
        )
        
        # 手動以非同步方式開啟連線池
        await langgraph_pool.open()
        
        checkpointer = AsyncPostgresSaver(langgraph_pool)
        
        # 自動建立 LangGraph 需要的記憶體資料表 (checkpoints, checkpoint_writes 等)
        await checkpointer.setup()
        print("✅ [Lifespan] LangGraph 企業級 Postgres 記憶體庫掛載成功！")

        # 3. 使用 settings 動態讀取 MCP 網址
        mcp_client = MultiServerMCPClient({
            "itops_tools": {
                "url": settings.MCP_SERVER_URL,
                "transport": "sse"
            }
        })
        
        mcp_tools = await mcp_client.get_tools()
        print(f"✅ [Lifespan] 成功於運作期迴圈中動態載入 {len(mcp_tools)} 把 MCP 工具！")
        
        # 4. 👈 【企業級新增 4】將工具與「記憶體(checkpointer)」注入大腦工廠
        agent_app = make_agent_app(mcp_tools, checkpointer=checkpointer)
        print("🚀 [Lifespan] LangGraph Agent 狀態機編譯完畢，微服務準備就緒。")
        
        yield
        
    except Exception as e:
        print("❌ [Lifespan Critical Error] 初始化階段遭遇崩潰:")
        traceback.print_exc()
        raise e
    finally:
        # 5. 優雅關閉所有連線
        if mcp_client:
            print("🛑 [Lifespan] 正在安全釋放 MCP 遠端微服務連線通道...")
            if hasattr(mcp_client, "close"):
                await mcp_client.close()
        if langgraph_pool:
            print("🛑 [Lifespan] 正在關閉 LangGraph 記憶體連線池...")
            await langgraph_pool.close()

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    thread_id: str
    message: str
    email: str

@app.post("/api/v1/chat")
async def chat_endpoint(request: ChatRequest):
    global agent_app
    if agent_app is None:
        raise HTTPException(status_code=503, detail="Agent 服務尚未初始化完成，請稍後再試。")
        
    try:
        # 🛡️ 【修正 1】把 recursion_limit 放寬到 15。
        # 正常的 RAG + 多工具呼叫通常需要 5~8 步，15 步是個安全的防呆值。
        config = {
            "configurable": {"thread_id": request.thread_id},
            "recursion_limit": 15 
        }
        input_message = HumanMessage(content=request.message)
        
        print(f"\n=============================================")
        print(f"🚀 [任務開始] 接收前端請求, Thread ID: {request.thread_id}")
        print(f"=============================================")

        async for chunk in agent_app.astream(
            {"messages": [input_message], "email": request.email}, 
            config, 
            stream_mode="updates"
        ):
            for node_name, node_data in chunk.items():
                print(f"\n🟢 [狀態機流轉] 抵達節點: {node_name}")
                
                # 🛡️ 【修正 2】安全檢查：如果 node_data 不是字典 (例如 __interrupt__ 節點)，就跳過不要印
                if not isinstance(node_data, dict):
                    print(f"  🛑 [系統訊號] 收到特殊中斷或控制訊號。")
                    continue
                    
                messages = node_data.get("messages", [])
                if not messages:
                    continue
                    
                last_msg = messages[-1]
                
                if node_name == "agent":
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tools = [tc["name"] for tc in last_msg.tool_calls]
                        print(f"  🧠 [大腦決策] 👉 準備呼叫工具: {tools}")
                    elif last_msg.content:
                        print(f"  🧠 [大腦對白] 👉 {str(last_msg.content)[:100]}...")
                        
                elif node_name in ["safe_tools", "sensitive_tools"]:
                    print(f"  🛠️ [工具回傳] 👉 {str(last_msg.content)[:100]}...")

        # 🎯 抓取最終記憶體狀態
        current_state = await agent_app.aget_state(config)
        messages = current_state.values.get("messages", [])
        last_message = messages[-1] if messages else None
        
        # 🚦 判斷系統是否處於凍結狀態
        if current_state.next:
            pending_tools = [tc["name"] for tc in last_message.tool_calls] if hasattr(last_message, 'tool_calls') else []
            final_response = f"⚠️ [系統凍結] 偵測到高風險操作，流程已暫停等待主管審批！(被攔截的動作: {pending_tools})"
        else:
            raw_content = last_message.content if last_message else ""
            if isinstance(raw_content, list) and len(raw_content) > 0 and isinstance(raw_content[0], dict):
                final_response = raw_content[0].get("text", str(raw_content))
            else:
                final_response = raw_content
        
        return {
            "status": "success",
            "thread_id": request.thread_id,
            "response": final_response,
            "is_suspended": len(current_state.next) > 0 
        }
        
    except Exception as e:
        print("❌ [API 運作期異常]:")
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)