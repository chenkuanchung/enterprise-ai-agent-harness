import os
from typing import Annotated, Sequence, List
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from src.rag.knowledge_base import search_it_sop
from src.agent.state import ITOpsAgentState

# ==========================================
# 動態載入技能檔 (Skills Injection)
# ==========================================
def load_skills() -> str:
    """
    在系統啟動時，動態讀取 skills.md 作為大腦的絕對行為守則。
    這樣未來修改流程，只需改 Markdown，不用動 Python 程式碼。
    """
    # 取得專案根目錄下的 docs/skills.md 路徑 (假設 graph.py 在 src/agent/ 下)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    skills_path = os.path.join(base_dir, "docs", "skills.md")
    
    try:
        with open(skills_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ [警告] 無法載入 skills.md: {e}")
        return "【警告：遺失技能檔，請要求工程師修復】"

# ==========================================
# 組合最終的大腦系統提示詞 (System Prompt)
# ==========================================
BASE_PROMPT = """你是一位專業的企業級 IT 維運助理 (ITOps Agent)。
你的核心職責是協助員工排除技術問題，並嚴格把關資安與簽核流程。

【核心運作邏輯】：
1. 遇到不確定的企業規定或風險分級 (Tier)，必須優先呼叫 `search_it_sop` 工具查詢法規。
2. 絕對禁止自行猜測簽核名單或竄改權限。

【強制技能與行為守則】：
以下是你必須嚴格遵守的操作指南。請依照使用者當下的請求，對照下方的技能守則來調用工具：

{skills_content}
"""

# 在模組載入時，將讀取到的 skills.md 內容注入到 Prompt 中
SYSTEM_PROMPT = BASE_PROMPT.format(skills_content=load_skills())


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
        """
        動態路由節點：檢查即將呼叫的工具是否屬於高風險操作。
        """
        messages = state.get("messages", [])
        if not messages:
            return END
        
        last_message = messages[-1]
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return END
            
        for tool_call in last_message.tool_calls:
            name = tool_call.get("name")
            args = tool_call.get("args", {})
            
            # 【Phase 2 優化】: update_ticket_status 不再視為需要凍結的敏感操作。
            # 將工單送交給主管 (Pending_Approval) 屬於安全流程。
            # 真正的敏感操作是 remote_wipe_device 等實體破壞性動作。
            if name in ["remote_wipe_device"]:
                print(f"⚠️ [HITL 觸發] 偵測到絕對高風險操作：{name}，強制凍結！")
                return "sensitive_tools"
                
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