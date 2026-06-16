import asyncio
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# 1. 載入 .env 中的環境變數 (如 GOOGLE_API_KEY)
load_dotenv()

# 2. 精確對齊：直接從 graph.py 匯入編譯好的全域變數 app
from src.agent.graph import app

async def main():
    # 3. 模擬使用者的問題
    user_input = "請幫我查一下設備 NB-RD-BOB-01 的健康狀態，如果容量不足請直接幫我清快取。"
    print(f"\n[User]: {user_input}")
    
    # 4. 封裝成 LangGraph 狀態機接收的初始 State 格式
    initial_state = {
        "messages": [HumanMessage(content=user_input)]
    }
    
    # 設定變數追蹤
    config = {"configurable": {"thread_id": "test_thread_01"}}
    
    print("\n--- 開始執行 Agent 狀態機 ---")
    
    # 5. 使用 astream 非同步串流執行，並印出每一個節點 (Node) 的回傳結果
    async for event in app.astream(initial_state, config):
        for node_name, state_update in event.items():
            print(f"\n>> 進入節點: {node_name}")
            # 印出該節點產生的最新一筆訊息
            if "messages" in state_update and state_update["messages"]:
                latest_msg = state_update["messages"][-1]
                
                # 判斷是工具調用請求還是文字回覆
                # 使用 hasattr 安全檢查物件是否具備 tool_calls 屬性
                if hasattr(latest_msg, 'tool_calls') and latest_msg.tool_calls:
                    print(f"大腦決定呼叫工具: {latest_msg.tool_calls}")
                else:
                    # ToolMessage (工具結果) 或是最終的 AIMessage (純文字) 都會印出 content
                    print(f"輸出內容: {latest_msg.content}")

if __name__ == "__main__":
    # 使用 asyncio 啟動非同步主程式
    asyncio.run(main())