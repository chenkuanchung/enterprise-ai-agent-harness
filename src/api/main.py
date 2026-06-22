from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
import uvicorn
import traceback
from contextlib import asynccontextmanager
from sqlalchemy import text 

from langchain_mcp_adapters.client import MultiServerMCPClient
from src.agent.graph import make_agent_app
from src.core.config.settings import settings
from src.db.session import AsyncSessionLocal 
from sqlalchemy.future import select
from src.db.models import User, ChatThread, Device

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
    
    # 檢查並自動建立側邊欄 ChatThread 紀錄
    async with AsyncSessionLocal() as session:
        try:
            # 1. 檢查這個 thread_id 是否已經在側邊欄資料庫裡
            thread_res = await session.execute(select(ChatThread).filter_by(thread_id=request.thread_id))
            existing_thread = thread_res.scalars().first()

            # 2. 如果是全新的對話，自動幫使用者建檔
            if not existing_thread:
                user_res = await session.execute(select(User).filter_by(email=request.email))
                user_obj = user_res.scalars().first()

                if user_obj:
                    # 擷取使用者第一句話的前 20 個字當作側邊欄標題
                    first_msg = request.message if request.action == "chat" else "未命名對話"
                    short_title = first_msg[:20] + ("..." if len(first_msg) > 20 else "")
                    
                    new_thread = ChatThread(
                        thread_id=request.thread_id,
                        tenant_id=user_obj.tenant_id,
                        user_id=user_obj.id,
                        title=short_title
                    )
                    session.add(new_thread)
                    await session.commit()
        except Exception as e:
            print(f"❌ 無法寫入 ChatThread 紀錄: {e}")
        
    async def event_generator():
        try:
            config = {"configurable": {"thread_id": request.thread_id}, "recursion_limit": 15}
            
            # 🚦 1. 檢查凍結狀態與 HITL 動作 (昨天完成的選項 A 邏輯)
            current_state = await agent_app.aget_state(config)
            is_suspended = len(current_state.next) > 0
            input_data = None 

            if is_suspended:
                if request.action == "approve":
                    # 🛡️ 企業級 ABAC 防線：不看 Role，看「動態資源權限」
                    
                    # 1. 取出 AI 當下被凍結的「危險工具呼叫」
                    messages = current_state.values.get("messages", [])
                    if not messages:
                        yield f"data: {json.dumps({'type': 'error', 'content': '無法取得歷史訊息以驗證操作。'})}\n\n"
                        return
                    last_msg = messages[-1]
                    tool_calls = getattr(last_msg, "tool_calls", [])
                    
                    if not tool_calls:
                        yield f"data: {json.dumps({'type': 'error', 'content': '無法識別待執行的操作。'})}\n\n"
                        return

                    async with AsyncSessionLocal() as session:
                        # 2. 查詢當前請求的員工
                        user_res = await session.execute(select(User).filter_by(email=request.email))
                        user_obj = user_res.scalars().first()

                        if not user_obj:
                            yield f"data: {json.dumps({'type': 'error', 'content': '身分驗證失敗。'})}\n\n"
                            return
                        
                        # 3. 根據不同的危險工具，實作不同的業務權限檢驗
                        all_tools_validated = True  # 預設防線狀態

                        for tool in tool_calls:
                            tool_name = tool["name"]
                            args = tool.get("args", {})

                            if tool_name == "remote_wipe_device":
                                device_id = args.get("device_id")
                                device_res = await session.execute(select(Device).filter_by(device_id=device_id))
                                device = device_res.scalars().first()
                                
                                if not device:
                                    yield f"data: {json.dumps({'type': 'error', 'content': f'找不到設備 {device_id}。'})}\n\n"
                                    return

                                if device.owner_id != user_obj.id:
                                    error_msg = f"❌ 資安攔截：您 ({user_obj.email}) 非設備 {device_id} 之擁有者，無權授權抹除操作。"
                                    yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
                                    return
                                    
                            # 如果未來有新工具，寫在這裡 elif...
                            
                            else:
                                # 🛑 觸發 Default Deny：遇到系統不認識的敏感工具，一律擋下！
                                all_tools_validated = False
                                yield f"data: {json.dumps({'type': 'error', 'content': f'❌ 資安攔截：未知的敏感操作 ({tool_name})，系統拒絕放行。'})}\n\n"
                                return

                        # 4. 驗證全數通過，正式放行大腦執行
                        if all_tools_validated:
                            yield f"data: {json.dumps({'type': 'status', 'content': '✅ 權限驗證通過，授權系統放行操作...'})}\n\n"
                            input_data = None

                elif request.action == "reject":
                    # 👈 【保留原本的駁回邏輯】：讓 LangGraph 知道操作被取消了
                    yield f"data: {json.dumps({'type': 'status', 'content': '❌ 已取消，正在退回大腦重新思考...'})}\n\n"
                    last_msg = current_state.values.get("messages", [])[-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tool_call = last_msg.tool_calls[0]
                        reject_msg = ToolMessage(
                            tool_call_id=tool_call["id"],
                            name=tool_call["name"],
                            content="⚠️ 此操作已被使用者手動取消與駁回。"
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

# ----------------------------------------------------
# 對話管理 API (重新命名、釘選、軟刪除)
# ----------------------------------------------------
class ThreadUpdateRequest(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None

@app.patch("/api/v1/threads/{thread_id}")
async def update_thread(thread_id: str, request: ThreadUpdateRequest):
    """[企業級功能] 重新命名或切換釘選狀態"""
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(ChatThread).filter_by(thread_id=thread_id, is_active=True))
            thread = res.scalars().first()
            if not thread:
                raise HTTPException(status_code=404, detail="找不到此對話")
            
            if request.title is not None:
                thread.title = request.title
            if request.is_pinned is not None:
                thread.is_pinned = request.is_pinned
                
            await session.commit()
            return {"status": "success", "message": "更新成功"}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """[企業級功能] 軟刪除對話紀錄"""
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(ChatThread).filter_by(thread_id=thread_id))
            thread = res.scalars().first()
            if not thread:
                raise HTTPException(status_code=404, detail="找不到此對話")
            
            # 企業級做法：軟刪除 (Soft Delete)，保留供資安稽核
            thread.is_active = False 
            await session.commit()
            return {"status": "success", "message": "已刪除對話"}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/threads")
async def get_user_threads(email: str):
    """
    [前端 UI 支援] 取得特定使用者的所有對話紀錄 (包含系統主動通知)
    """
    async with AsyncSessionLocal() as session:
        try:
            # 1. 驗證使用者
            user_res = await session.execute(select(User).filter_by(email=email))
            user_obj = user_res.scalars().first()
            if not user_obj:
                raise HTTPException(status_code=404, detail="找不到該使用者")

            # 2. 撈取對話紀錄：優先顯示釘選，再依更新時間排序
            threads_res = await session.execute(
                select(ChatThread)
                .filter_by(user_id=user_obj.id, is_active=True)
                .order_by(ChatThread.is_pinned.desc(), ChatThread.updated_at.desc()) # 👈 排序邏輯升級
            )
            threads = threads_res.scalars().all()

            thread_list = [
                {
                    "thread_id": t.thread_id,
                    "title": t.title,
                    "is_pinned": t.is_pinned,  # 👈 新增回傳
                    "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M")
                }
                for t in threads
            ]

            return {"status": "success", "threads": thread_list}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/api/v1/chat/history")
async def get_chat_history(thread_id: str):
    """
    [前端 UI 支援] 根據 Thread ID 從 LangGraph 記憶體中完整還原歷史對話
    """
    global agent_app
    if not agent_app:
        raise HTTPException(status_code=503, detail="Agent 尚未初始化")

    try:
        # 1. 取得 LangGraph 針對該 thread 的完整狀態
        config = {"configurable": {"thread_id": thread_id}}
        state = await agent_app.aget_state(config)

        # 若查無歷史紀錄
        if not state or not hasattr(state, "values") or "messages" not in state.values:
            return {"status": "success", "messages": []}

        raw_messages = state.values["messages"]
        formatted_messages = []

        # 2. 濾除不必要的系統訊息，並轉換為前端需要的格式
        for idx, msg in enumerate(raw_messages):
            if isinstance(msg, SystemMessage) or isinstance(msg, ToolMessage):
                continue  # 前端不需要顯示 System Prompt 與純工具回傳值

            role = "user" if isinstance(msg, HumanMessage) else "agent"

            # 提取內容字串
            content = ""
            if isinstance(msg.content, str):
                content = msg.content
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if isinstance(item, str):
                        content += item
                    elif isinstance(item, dict) and "text" in item:
                        content += item["text"]

            # 若 AI 只有呼叫工具而沒有文字內容，則不顯示該對話氣泡
            if not content.strip():
                continue

            formatted_messages.append({
                "id": f"hist-{idx}",
                "role": role,
                "content": content
            })

        # 3. 🎯 核心體驗：如果該對話目前處於「凍結」狀態，則為最後一句話加上 isSuspended 標記
        is_suspended = len(state.next) > 0
        if is_suspended and formatted_messages:
            formatted_messages[-1]["isSuspended"] = True

        return {
            "status": "success", 
            "messages": formatted_messages,
            "is_suspended": is_suspended
        }

    except Exception as e:
        print("❌ [History Error]:", e)
        raise HTTPException(status_code=500, detail="無法撈取歷史對話")

if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)