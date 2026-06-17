import requests
import json
import time

API_URL = "http://127.0.0.1:8000/api/v1/chat"
THREAD_ID = "demo-ticket-011" # 記得確保這是一個新的房間

print("=====================================================")
print("🛡️ 企業級 AI Agent：兩階段授權與 HITL 攔截測試")
print("=====================================================\n")

# ---------------------------------------------------------
# 💬 第一回合：Bob 提出申請
# ---------------------------------------------------------
payload1 = {
    "thread_id": THREAD_ID,
    "message": "我是 Bob Lee，因為專案需求，我要申請安裝 Navicat 軟體。",
    "email": "bob.lee@globaltech.com"
}
print(f"👤 [員工 Bob] (第一回合): {payload1['message']}")
print("⏳ (Agent 正在查詢 SOP，並準備開單詢問確認...)\n")

res1 = requests.post(API_URL, json=payload1).json()
print("🤖 [Agent 回覆]:")
print(res1.get("response", "無文字回覆"))
print("-" * 50)

# 如果系統在這裡就被凍結，代表 AI 沒聽話偷跑了
if res1.get("is_suspended"):
    print("❌ 錯誤：AI 沒有問使用者，直接偷跑觸發了攔截！")
    exit()

time.sleep(2) # 停頓兩秒，模擬人類閱讀時間

# ---------------------------------------------------------
# 💬 第二回合：Bob 看完工單資訊，點擊「確認」
# ---------------------------------------------------------
print("\n👤 [員工 Bob] (第二回合): 資訊無誤，我確認送出審批！")
print("⏳ (Agent 收到授權，準備變更狀態並觸發海關攔截...)\n")

payload2 = {
    "thread_id": THREAD_ID,
    "message": "資訊無誤，我確認送出審批！",
    "email": "bob.lee@globaltech.com"
}
res2 = requests.post(API_URL, json=payload2).json()

print("🤖 [系統最終狀態]:")
if res2.get("is_suspended"):
    print(f"✅ 完美成功！系統回傳: {res2.get('response')}")
else:
    print("❌ 錯誤：系統沒有被攔截，請檢查 LangGraph 路由設定。")