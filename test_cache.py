from src.cache.semantic_cache import semantic_cache

def handle_user_request(user_message: str):
    print(f"\n[使用者提問]: {user_message}")
    
    # 1. 攔截點：優先查詢語意快取
    cached_response = semantic_cache.check(prompt=user_message)
    if cached_response:
        print("[系統回覆 - ⚡極速快取]:")
        return cached_response
        
    # 2. 如果沒有命中，才去呼叫 LangGraph (模擬消耗資源的過程)
    print("⏳ [Cache MISS] 未命中快取，正在喚醒 LangGraph 與 LLM 進行完整運算...")
    
    # ... 這裡原本是呼叫 Agent 運算並取得答案的程式碼 ...
    # 假設 LLM 經過 5 秒思考後，得出了以下答案：
    final_llm_answer = "根據 RD-001 規定，您必須取得 Senior Engineer 主管同意才能安裝 Docker。"
    print("[系統回覆 - 🧠LLM 運算]:")
    print(final_llm_answer)
    
    # 3. 把辛苦算出來的答案存進快取，造福後人
    semantic_cache.store(prompt=user_message, response=final_llm_answer)
    
    return final_llm_answer

# --- 測試體驗 ---
if __name__ == "__main__":
    # 第一次問：觸發 LLM 運算並存入快取
    handle_user_request("我想申請 Docker 權限，有規定嗎？")
    
    print("-" * 40)
    
    # 第二次問：語意改變，但核心意思一樣，應該要瞬間命中快取！
    handle_user_request("請問申請安裝 Docker 有沒有什麼特殊規定需要遵守？")