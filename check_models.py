# import os
# from dotenv import load_dotenv
# from google import genai

# # 1. 載入環境變數中的 GOOGLE_API_KEY
# load_dotenv()

# # 2. 初始化最新版 SDK 的 Client
# client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# print("🔍 正在向 Google 伺服器查詢您的金鑰目前可用的 Embedding 模型...\n")

# try:
#     # 3. 呼叫 API 取得所有模型清單
#     models = client.models.list()
    
#     found = False
#     for m in models:
#         # 篩選出名稱中包含 'embed' 的模型
#         if "embed" in m.name.lower():
#             print(f"✅ 發現可用模型: {m.name}")
#             found = True
            
#     if not found:
#         print("⚠️ 查無任何 Embedding 模型，請確認您的 API Key 權限或帳號狀態。")
        
# except Exception as e:
#     print(f"🚨 查詢失敗，錯誤訊息: {e}")




import os
from dotenv import load_dotenv
from google import genai

# 1. 載入環境變數中的 GOOGLE_API_KEY
load_dotenv()

# 2. 初始化最新版 SDK 的 Client
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("🔍 正在向 Google 伺服器查詢您的金鑰目前可用的「生成式」模型...\n")

try:
    # 3. 呼叫 API 取得所有模型清單
    models = client.models.list()
    
    found = False
    for m in models:
        # 篩選條件：排除名稱中包含 'embed' 的模型
        if "embed" not in m.name.lower():
            # 這裡也可以多加上 print(f"   - 描述: {m.display_name}") 來查看更詳細的名稱
            print(f"✅ 發現可用模型: {m.name}")
            found = True
            
    if not found:
        print("⚠️ 查無任何可用的生成式模型，請確認您的 API Key 權限或帳號狀態。")
        
except Exception as e:
    print(f"🚨 查詢失敗，錯誤訊息: {e}")