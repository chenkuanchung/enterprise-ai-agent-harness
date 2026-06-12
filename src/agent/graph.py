import os
from typing import Literal
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

# 匯入我們自己寫的配置、記憶體與工具
from src.core.config.settings import settings
from src.agent.state import ITOpsAgentState
from src.agent.tools import IT_OPS_TOOLS

# ==========================================
# 1. 初始化 LLM 大腦與綁定工具
# ==========================================

# 確保已經讀取到 Gemini API Key (POC 階段主力模型)
os.environ["GOOGLE_API_KEY"] = settings.GOOGLE_API_KEY

# 初始化 Gemini 模型
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash", # 使用高性價比的 flash 模型
    temperature=0.0,          # 維運場景嚴禁幻覺，將創意度降到最低
)

# 將我們的 11 個 IT 維運工具綁定給 LLM，讓它知道有哪些遙控器可以用
llm_with_tools = llm.bind_tools(IT_OPS_TOOLS)


# ==========================================
# 2. 定義 System Prompt (系統提示詞與 Guardrails)
# ==========================================

SYSTEM_PROMPT = """你是一位任職於大型科技企業的「頂級 IT 維運專家 (ITOps Agent)」。
你的唯一職責是協助員工排解 IT 設備、帳號權限與系統服務的故障問題。

【最高行為準則 Guardrails】
1. 邊界控制：絕對拒絕回答任何與 IT 維運無關的問題（如寫程式、閒聊、寫文章）。若遇到此類問題，請禮貌地回覆：「我是 IT 維運助理，僅能協助您處理系統與設備問題。」
2. 動作前查證：在執行任何具備風險的操作（如重啟伺服器、遠端抹除）之前，必須先呼叫 `get_asset_dependencies` 查詢影響範圍。
3. 嚴謹修復：如果員工要求解鎖帳號，必須先呼叫 `check_account_status` 確認真的被鎖定才能解鎖。
4. 工單閉環：處理完使用者的問題後，請務必記得呼叫 `resolve_ticket` 或 `update_ticket_status` 來更新狀態，並在回覆中告訴使用者處置結果。

請基於上述準則，專業、簡潔地為使用者排除故障。"""


# ==========================================
# 3. 定義 Graph Nodes (節點邏輯)
# ==========================================

def call_model(state: ITOpsAgentState):
    """
    大腦思考節點：將當前狀態與對話歷史交給 LLM，讓它決定要說什麼或用什麼工具。
    """
    messages = state["messages"]
    
    # 如果對話是空的，或是第一句話不是 SystemMessage，我們就偷偷把系統提示詞塞進去
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        
    # 呼叫綁定好工具的 LLM
    response = llm_with_tools.invoke(messages)
    
    # 將 LLM 的回覆 (可能是文字，也可能是 Tool Call 請求) 回傳，LangGraph 會自動加進 state
    return {"messages": [response]}


# 使用 LangGraph 內建的 ToolNode，它會自動讀取 LLM 發出的請求去執行對應的 Python 函式
tool_node = ToolNode(IT_OPS_TOOLS)


# ==========================================
# 4. 定義路由邏輯 (Conditional Edges)
# ==========================================

def should_continue(state: ITOpsAgentState) -> Literal["tools", END]:
    """
    路由判斷：檢查 LLM 剛剛的回覆中，是否包含「呼叫工具的請求」。
    """
    last_message = state["messages"][-1]
    
    # 如果 LLM 決定要用工具，就把流程導向 "tools" 節點
    if last_message.tool_calls:
        return "tools"
    
    # 如果 LLM 沒有要用工具（代表它已經查完資料，正在跟人類講話），就結束這回合思考
    return END


# ==========================================
# 5. 組裝大腦神經網路 (StateGraph)
# ==========================================

workflow = StateGraph(ITOpsAgentState)

# 加入節點 (定義地圖上有哪些房間)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

# 設定起點：只要收到新訊息，第一步永遠是交給 Agent 大腦思考
workflow.add_edge(START, "agent")

# 設定條件路由：Agent 思考完後，該去執行工具，還是直接把答案輸出給人類？
workflow.add_conditional_edges("agent", should_continue)

# 設定工具執行完的下一步：執行完工具後，把結果丟回給 Agent 大腦，讓它看著結果繼續思考
workflow.add_edge("tools", "agent")

# 編譯成可執行的應用程式 (這裡我們先不加上 Checkpointer，等接到 API 層時再加)
app = workflow.compile()