import os
from typing import Annotated, Sequence, List
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from src.rag.knowledge_base import search_it_sop
from src.agent.state import ITOpsAgentState

# 【企業級維運大腦守則】
SYSTEM_PROMPT = """你是一位專業的 IT 維運助理 (ITOps Agent)。
你的職責是協助員工排除技術問題。

【企業級維運處理守則】：
1. 查詢規定 (RAG)：遇到任何不確定的規定或SOP，必須優先使用 search_it_sop 工具。
2. 開單時機 (Ticketing)：
   - 若使用者僅是「一般問題諮詢」或「查詢規定」，直接回答即可，【絕對不要】開立工單。
   - 若使用者要求「執行變更、申請軟體、排除故障」，請務必呼叫 create_ticket 建立工單追蹤。
3. 狀態流轉與確認 (Status Lifecycle)：
   - 執行修復動作後，請將工單狀態更新為 'Resolved'，並主動詢問使用者是否解決。
   - 收到正向回覆後，才能將狀態更新為 'Closed'。
4. 高風險防護 (HITL)：
   - 處理涉及安全風險的操作 (如 Tier 4 軟體、遠端抹除) 時，請嚴格遵守【兩階段確認流程】：
     👉 第一步：先呼叫 create_ticket 建立工單。然後向使用者列出工單編號與申請內容，並【主動詢問】：「請問是否確認送交主管審批？」。(此時不可呼叫 update_ticket_status)
     👉 第二步：必須收到使用者明確的「確認」回覆後，才能呼叫 update_ticket_status 將狀態改為 'Pending_Approval'。
"""

def make_agent_app(mcp_tools: List, checkpointer=None):
    """
    企業級 Agent 工廠：負責接收受控的遠端工具鏈，動態建構並編譯 LangGraph 狀態機。
    """

    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        print(f"🔑 [Security Check] 大腦拿到的金鑰: {api_key[:5]}...{api_key[-5:]}")

    # 確保在運行期擁有完整環境變數
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite",
        temperature=0.0,
        google_api_key=os.getenv("GOOGLE_API_KEY")
    )
    
    # 把 MCP 的遠端工具，和本地的 RAG 工具合併！
    all_tools = mcp_tools + [search_it_sop]
    
    # 將工具綁定至大腦
    llm_with_tools = llm.bind_tools(all_tools)

    async def call_model(state: ITOpsAgentState):
        """大腦思考節點"""
        messages = state["messages"]
        # 從 State 取出前端傳來的信箱
        email = state.get("email", "未知") 
        
        # 告訴大腦使用者的信箱
        dynamic_prompt = SYSTEM_PROMPT + f"\n\n【當前環境上下文】\n目前登入系統的員工信箱為: {email}"
        
        filtered_messages = [m for m in messages if not isinstance(m, SystemMessage)]
        invoke_messages = [SystemMessage(content=dynamic_prompt)] + filtered_messages
            
        response = await llm_with_tools.ainvoke(invoke_messages)
        return {"messages": [response]}

    # 🚦 【企業級動態路由】檢測 AI 的決策是否觸發安全邊界
    def route_tools(state: ITOpsAgentState):
        """條件路由節點：解析 AI 工具呼叫的參數，動態決定是否放行"""
        messages = state["messages"]
        last_message = messages[-1]
        
        # 如果大腦沒有要呼叫工具，就結束對話
        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return END
            
        # 逐一檢查大腦準備呼叫的工具與其「參數」
        for tool_call in last_message.tool_calls:
            name = tool_call["name"]
            args = tool_call.get("args", {})
            
            # 絕對地雷 1：只要是呼叫遠端抹除，不管什麼理由，強制凍結審批
            if name == "remote_wipe_device":
                print(f"⚠️ [HITL 觸發] 偵測到絕對高風險操作：{name}，強制凍結！")
                return "sensitive_tools"
                
            # 絕對地雷 2 (AI 動態決策的體現)：
            # AI 查閱 SOP 後，若「決定」將工單改為 'Pending_Approval'，系統才介入凍結。
            # 若 AI 是將工單改為 'Resolved' 或 'Closed' 等安全狀態，則視為安全操作，直接放行。
            if name == "update_ticket_status":
                if args.get("status") == "Pending_Approval":
                    print(f"⚠️ [HITL 觸發] AI 判斷該任務需主管簽核 (狀態: Pending_Approval)，啟動凍結機制！")
                    return "sensitive_tools"
                else:
                    print(f"✅ [安全放行] 變更工單狀態為：{args.get('status')}，不需 HITL。")
                
        # 通過所有檢查，走綠色通道放行
        return "safe_tools"

    # 組合狀態機地圖
    workflow = StateGraph(ITOpsAgentState)
    workflow.add_node("agent", call_model)
    
    # 建立兩個一模一樣的工具節點，但掛載在不同的路由上
    workflow.add_node("safe_tools", ToolNode(all_tools))
    workflow.add_node("sensitive_tools", ToolNode(all_tools))

    workflow.add_edge(START, "agent")
    
    # 掛載動態分流器
    workflow.add_conditional_edges("agent", route_tools, {
        "safe_tools": "safe_tools",
        "sensitive_tools": "sensitive_tools",
        END: END
    })
    
    # 工具執行完畢後，不管哪條路徑都回到大腦
    workflow.add_edge("safe_tools", "agent")
    workflow.add_edge("sensitive_tools", "agent")

    # 🔒 【核心防線】只在 sensitive_tools 前面踩煞車，並接收外部傳入的 PostgreSQL checkpointer
    return workflow.compile(
        checkpointer=checkpointer, 
        interrupt_before=["sensitive_tools"]
    )