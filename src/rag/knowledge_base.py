import os
import re
import shutil
import hashlib
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.tools import tool
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from src.cache.semantic_cache import semantic_cache

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOP_FILE_PATH = BASE_DIR / "docs" / "it_sop.md"
CHROMA_PERSIST_DIR = BASE_DIR / "chroma_data"
HASH_FILE_PATH = CHROMA_PERSIST_DIR / "file_hash.txt"

print("🛡️ [Enterprise RAG] 正在啟動高可用混合檢索核心...")

# ---------------------------------------------------------------------------
# 企業級技術落實 1：高相容性中英文混合分詞器 (處理企業黑話與特殊工單編號)
# ---------------------------------------------------------------------------
def enterprise_chinese_tokenizer(text: str) -> List[str]:
    """
    專為 IT 維運設計的分詞器。
    確保 'RD-001', 'Docker', 'ERR-7788' 等關鍵詞不被切碎，同時將中文字元單獨切分以利 BM25 精確匹配。
    """
    # 萃取英文、數字、連字號組成的連續字串 (如 RD-001, Docker)
    tokens = re.findall(r'[a-zA-Z0-9\-]+', text)
    # 清除英文後的殘留中文字，並逐字切分
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return tokens + chinese_chars

def get_file_md5(file_path: Path) -> str:
    if not file_path.exists():
        return ""
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

# ---------------------------------------------------------------------------
# 企業級技術落實 2：智慧型持久化與快取指紋驗證管線
# ---------------------------------------------------------------------------
current_hash = get_file_md5(SOP_FILE_PATH)
should_rebuild = False

if CHROMA_PERSIST_DIR.exists():
    old_hash = HASH_FILE_PATH.read_text().strip() if HASH_FILE_PATH.exists() else ""
    if current_hash != old_hash:
        print("⚡ [Enterprise RAG] 檢測到 SOP 基準文件變更，觸發自動銷毀重建機制...")
        shutil.rmtree(CHROMA_PERSIST_DIR)
        semantic_cache.flush_all() # SOP 改變了，舊的回答全部作廢，強制清除 Redis 快取！
        should_rebuild = True
    else:
        should_rebuild = False
else:
    should_rebuild = True

# 初始化 2026 最新生成式 AI 嵌入模型
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-2",
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# 宣告全域檢索器變數，供 Tool 呼叫
ensemble_retriever = None

# 讀取並切割文檔 (無論是重建還是首次建置都需要文檔區塊來初始化 BM25)
if not SOP_FILE_PATH.exists():
    raise FileNotFoundError(f"核心錯誤：未能在指定路徑尋獲 SOP 文件：{SOP_FILE_PATH}")

loader = TextLoader(str(SOP_FILE_PATH), encoding="utf-8")
raw_documents = loader.load()

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=50,
    separators=["\n## ", "\n- ", "\n\n", "\n", " ", ""]
)
docs_chunks = text_splitter.split_documents(raw_documents)

if not docs_chunks:
    raise ValueError("核心錯誤：文檔切塊結果為空，請檢查原始 MD 檔。")

if not should_rebuild:
    print("📦 [Enterprise RAG] 數位指紋對齊一致。直接加載本地 ChromDB 儲存庫...")
    vector_store = Chroma(
        collection_name="it_sop_collection",
        embedding_function=embeddings,
        persist_directory=str(CHROMA_PERSIST_DIR)
    )
else:
    print("📚 [Enterprise RAG] 正在為全新文檔進行多維度矩陣向量化空間建置...")
    vector_store = Chroma.from_documents(
        documents=docs_chunks,
        embedding=embeddings,
        collection_name="it_sop_collection",
        persist_directory=str(CHROMA_PERSIST_DIR)
    )
    HASH_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE_PATH.write_text(current_hash)
    print("✅ [Enterprise RAG] ChromaDB 向量矩陣建置完畢並成功落地。")

# ---------------------------------------------------------------------------
# 企業級技術落實 3：實作雙軌動態融合檢索 (Dense Vector + Sparse BM25 via RRF)
# ---------------------------------------------------------------------------
print("🚀 [Enterprise RAG] 正在初始化 BM25 稀疏矩陣並配置 RRF 融合權重...")

# 建立 1:1 的向量與關鍵字雙軌檢索器
chroma_retriever = vector_store.as_retriever(search_kwargs={"k": 2})
bm25_retriever = BM25Retriever.from_documents(
    documents=docs_chunks,
    preprocess_func=enterprise_chinese_tokenizer # 掛載我們寫好的企業級中英分詞器
)
bm25_retriever.k = 2

# 使用 EnsembleRetriever 將兩者打包，內部自動執行 RRF 演算法
# weights=[0.5, 0.5] 代表語意泛化與關鍵字精確度具有同等最高優先權
ensemble_retriever = EnsembleRetriever(
    retrievers=[chroma_retriever, bm25_retriever],
    weights=[0.5, 0.5]
)

print("🏆 [Enterprise RAG] 雙軌混合檢索引擎建置成功，生產環境規格解鎖。")

# ---------------------------------------------------------------------------
# 4. 封裝成大腦專屬武器
# ---------------------------------------------------------------------------
@tool
def search_it_sop(query: str) -> str:
    """
    [生產環境級別工具] 搜尋公司內部 IT 維運標準作業程序 (SOP) 文件庫。
    此工具採用 Hybrid Search (Chroma 語意向量 + BM25 精確關鍵字) 與 RRF 融合排序演算法。
    當遇到的提問涉及：特定表單編號(如 RD-001)、技術名詞、操作權限規範、硬體空間限制數字時，
    必須優先且強制執行此工具以取得絕對正確的合規判定基準。
    """
    # 調用全域 RRF 檢索器
    retrieved_docs = ensemble_retriever.invoke(query)
    
    if not retrieved_docs:
        return "【SOP 文件檢索結果】未在知識庫中尋獲與查詢關聯之合規條文。"
        
    result_text = "\n\n".join([f"[(區塊)] {doc.page_content}" for doc in retrieved_docs])
    return f"【SOP 雙軌混合檢索結果 (RRF 排序已啟用)】\n{result_text}"