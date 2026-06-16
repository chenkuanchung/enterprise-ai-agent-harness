import requests

API_URL = "http://127.0.0.1:8000/api/v1/chat"
# 我們指定一個固定的對話 ID
THREAD_ID = "memory-test-001" 

print("=====================================")
print("🧠 LangGraph 記憶體 (Checkpointer) 測試")
print("=====================================\n")

# --- 第一回合：建立上下文 ---
payload_1 = {
    "thread_id": THREAD_ID,
    "message": "你好，我是研發部的 Bob。請記住我的分機號碼是 7788。"
}
print(f"[User]: {payload_1['message']}")
response_1 = requests.post(API_URL, json=payload_1)
print(f"[Agent]: {response_1.json()['response']}\n")

# --- 第二回合：挑戰 RAG 知識庫與規定 ---
payload_2 = {
    "thread_id": THREAD_ID,
    # 這裡的 Docker 規定是我們在 it_sop.md 裡特別設計的陷阱題
    "message": "我是研發部的 Bob。我最近專案需要，想要申請安裝 Docker，請問可以幫我裝嗎？有什麼規定？"
}

print(f"[User]: {payload_2['message']}")
response_2 = requests.post(API_URL, json=payload_2)
print(f"[Agent]: {response_2.json()['response']}\n")