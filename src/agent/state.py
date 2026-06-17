from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class ITOpsAgentState(TypedDict):
    """
    IT 維運 Agent 的狀態機記憶體 (State)。
    這是在 LangGraph 節點之間傳遞的唯一資料結構。
    """
    # 1. 核心對話紀錄：add_messages 會確保新訊息自動 append 到歷史紀錄後
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 2. 業務上下文 (Context)
    ticket_id: Optional[str]       # 目前正在處理的工單編號 (一開始可能是 None)
    
    # 3. 審批控制 (HITL 機制)
    requires_approval: bool        # 標記當前操作是否需要主管簽核

    email: str