import os
from dotenv import load_dotenv
from pydantic import PrivateAttr
from redisvl.extensions.llmcache import SemanticCache
from redisvl.utils.vectorize.base import BaseVectorizer
from langchain_google_genai import GoogleGenerativeAIEmbeddings

load_dotenv()

# 企業級轉接器：強制 RedisVL 使用我們的 Gemini 模型
class GeminiVectorizer(BaseVectorizer):
    # 明確宣告這是一個私有屬性，避開 Pydantic 的嚴格檢查
    _embeddings: object = PrivateAttr()

    def __init__(self, embeddings):
        # 宣告 Gemini 2 的標準輸出維度 3072
        super().__init__(model="gemini-embedding-2", dims=3072)
        self._embeddings = embeddings

    def embed(self, text: str, **kwargs) -> list[float]:
        return self._embeddings.embed_query(text)

    def embed_many(self, texts: list[str], **kwargs) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

class ITOPSSemanticCache:
    def __init__(self):
        print("⚡ [Cache] 正在初始化 Redis 語意快取層...")
        
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        
        # 實例化我們的轉接器
        gemini_vectorizer = GeminiVectorizer(self.embeddings)
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
        # 將轉接器正式掛載到 SemanticCache，徹底阻斷 HF 下載
        self.cache = SemanticCache(
            name="itops_query_cache",
            redis_url=redis_url,
            distance_threshold=0.12,
            vectorizer=gemini_vectorizer 
        )

    def check(self, prompt: str) -> str | None:
        """檢查是否有高度相似的歷史解答"""
        try:
            # 將使用者的文字轉換成向量
            vector = self.embeddings.embed_query(prompt)
            # 交給 Redis 進行極速相似度比對
            result = self.cache.check(vector=vector)
            if result:
                print(f"🎯 [Cache HIT] 語意快取命中！成功攔截相似提問。")
                return result[0]['response']
            return None
        except Exception:
            return None

    def store(self, prompt: str, response: str):
        """將 LLM 產生的標準答案存入快取"""
        try:
            vector = self.embeddings.embed_query(prompt)
            self.cache.store(prompt=prompt, response=response, vector=vector)
            print(f"💾 [Cache STORE] 新提問已寫入 Redis 快取記憶體。")
        except Exception as e:
            print(f"⚠️ [Cache STORE] 寫入失敗: {e}")

    def flush_all(self):
        """危急與更新時刻：清空所有快取"""
        try:
            self.cache.clear()
            print("💥 [Cache FLUSH] 已徹底清空 Redis 語意快取，避免提供過期資訊！")
        except Exception as e:
            print(f"⚠️ [Cache FLUSH] 清空失敗: {e}")

# 實例化單例 (Singleton) 供全域匯入使用
semantic_cache = ITOPSSemanticCache()