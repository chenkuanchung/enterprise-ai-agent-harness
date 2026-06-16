import os
from typing import Annotated, Sequence, List
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from src.rag.knowledge_base import search_it_sop

# 定義狀態機資料結構
class ITOpsAgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]

SYSTEM_PROMPT = """你是一位專業的 IT 維運助理 (ITOps Agent)。
你的職責是協助員工排除技術問題。
【最高指導原則】：你不預設知道任何公司規定。只要遇到操作判斷、軟體安裝、權限申請等規定詢問，請務必先使用 search_it_sop 工具查詢標準作業程序，再進行回答或執行其他 MCP 工具。
"""

def make_agent_app(mcp_tools: List):
    """
    企業級 Agent 工廠：負責接收受控的遠端工具鏈，動態建構並編譯 LangGraph 狀態機。
    """
    # 確保在運行期擁有完整環境變數
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
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
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
            
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # 使用動態注入的工具鏈建立 ToolNode
    tool_node = ToolNode(all_tools)

    def should_continue(state: ITOpsAgentState):
        """條件路由節點"""
        messages = state["messages"]
        last_message = messages[-1]
        if not last_message.tool_calls:
            return END
        return "tools"

    # 組合狀態機地圖
    workflow = StateGraph(ITOpsAgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    # 掛載短期與長期記憶體
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)