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
from sqlalchemy.future import select
from src.db.models import User

# LangGraph Postgres 記憶體相關套件
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

import json
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, ToolMessage
from typing import Optional
import bcrypt

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

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/v1/auth/login")
async def login_endpoint(request: LoginRequest):
    # 這裡我們使用 FastAPI lifespan 中初始化的 AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            # 1. 查詢資料庫中的員工
            result = await session.execute(select(User).filter_by(email=request.email))
            user_obj = result.scalars().first()
            
            if not user_obj:
                raise HTTPException(status_code=401, detail="找不到此員工帳號")
                
            # 2. 核心防線：檢查帳號是否為 Active
            if user_obj.account_status != "Active":
                raise HTTPException(status_code=403, detail="登入失敗：此帳號已被鎖定或停權")
                
            # 3. 🛡️ 企業級防線：使用原生 bcrypt 比對密碼 Hash
            # 注意：輸入的明碼與資料庫抓出來的 hash，都必須轉成 bytes 才能比對
            if not bcrypt.checkpw(request.password.encode('utf-8'), user_obj.hashed_password.encode('utf-8')):
                raise HTTPException(status_code=401, detail="登入失敗：密碼錯誤")
                
            return {
                "status": "success",
                "user": {
                    "email": user_obj.email,
                    "name": user_obj.full_name,
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ 登入查詢錯誤: {e}")
            raise HTTPException(status_code=500, detail="資料庫連線異常")

class ChatRequest(BaseModel):
    thread_id: str
    message: str
    email: str
    action: Optional[str] = "chat" # 新增動作型別：chat (對話), approve (核准), reject (駁回)

@app.post("/api/v1/chat")
async def chat_endpoint(request: ChatRequest):
    global agent_app
    if agent_app is None:
        raise HTTPException(status_code=503, detail="Agent 服務尚未初始化完成，請稍後再試。")
        
    async def event_generator():
        try:
            config = {"configurable": {"thread_id": request.thread_id}, "recursion_limit": 15}
            
            # 🚦 1. 檢查凍結狀態與 HITL 動作 (昨天完成的選項 A 邏輯)
            current_state = await agent_app.aget_state(config)
            is_suspended = len(current_state.next) > 0
            input_data = None 

            if is_suspended:
                if request.action == "approve":
                    yield f"data: {json.dumps({'type': 'status', 'content': '✅ 授權成功，正在喚醒大腦執行任務...'})}\n\n"
                    input_data = None 
                elif request.action == "reject":
                    yield f"data: {json.dumps({'type': 'status', 'content': '❌ 已駁回，正在退回大腦重新思考...'})}\n\n"
                    last_msg = current_state.values.get("messages", [])[-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tool_call = last_msg.tool_calls[0]
                        reject_msg = ToolMessage(
                            tool_call_id=tool_call["id"],
                            name=tool_call["name"],
                            content="⚠️ 此操作已被主管或使用者手動駁回與取消。"
                        )
                        await agent_app.aupdate_state(config, {"messages": [reject_msg]}, as_node="sensitive_tools")
                    input_data = None
                else:
                    yield f"data: {json.dumps({'type': 'error', 'content': '系統處於凍結狀態，請先點擊授權或駁回。'})}\n\n"
                    return
            else:
                input_message = HumanMessage(content=request.message)
                input_data = {"messages": [input_message], "email": request.email}

            # 🚀 2. 啟動 LangGraph 雙軌流模式 (Token 串流 + 節點狀態)
            async for stream_type, chunk in agent_app.astream(input_data, config, stream_mode=["messages", "updates"]):
                
                # 【軌道 A】捕捉文字 Token (打字機效果)
                if stream_type == "messages":
                    msg_chunk, metadata = chunk
                    if metadata.get("langgraph_node") == "agent" and msg_chunk.content:
                        
                        # 🛡️ 型別清洗：確保 Gemini 回傳的複雜結構被展平為純字串
                        token_text = ""
                        if isinstance(msg_chunk.content, str):
                            token_text = msg_chunk.content
                        elif isinstance(msg_chunk.content, list):
                            for item in msg_chunk.content:
                                if isinstance(item, str):
                                    token_text += item
                                elif isinstance(item, dict) and "text" in item:
                                    token_text += item["text"]
                        
                        # 只有當萃取出實質文字時，才推送到前端
                        if token_text:
                            yield f"data: {json.dumps({'type': 'token', 'content': token_text})}\n\n"
                
                # 【軌道 B】捕捉節點與工具狀態 (讓前端顯示 "正在呼叫工具...")
                elif stream_type == "updates":
                    for node_name, node_data in chunk.items():
                        if not isinstance(node_data, dict):
                            continue # 忽略中斷訊號
                        
                        if node_name == "agent":
                            messages = node_data.get("messages", [])
                            if messages and hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
                                tools = [tc["name"] for tc in messages[-1].tool_calls]
                                yield f"data: {json.dumps({'type': 'status', 'content': f'🧠 準備呼叫工具: {tools}'})}\n\n"
                        elif node_name in ["safe_tools", "sensitive_tools"]:
                            yield f"data: {json.dumps({'type': 'status', 'content': '🛠️ 工具執行完畢，彙整結果中...'})}\n\n"

            # 🎯 3. 執行完畢，檢查最終狀態 (判斷是否觸發攔截)
            final_state = await agent_app.aget_state(config)
            if final_state.next:
                yield f"data: {json.dumps({'type': 'suspend'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'finish'})}\n\n"

        except Exception as e:
            print("❌ [Streaming Error]:", e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    # 使用 FastAPI 的 StreamingResponse 回傳 SSE 格式
    return StreamingResponse(event_generator(), media_type="text/event-stream")
    
if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)