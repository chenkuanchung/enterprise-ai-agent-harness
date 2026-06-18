"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Send, Bot, User, AlertTriangle, CheckCircle, XCircle, RefreshCw, LogOut } from "lucide-react";
import ReactMarkdown from "react-markdown";

type Message = {
  id: string;
  role: "user" | "agent";
  content: string;
  isSuspended?: boolean;
  statusText?: string;
  isStreaming?: boolean;
};

export default function Home() {
  const router = useRouter();
  
  // 狀態管理
  const [currentUser, setCurrentUser] = useState<{name: string, email: string} | null>(null);
  const [threadId, setThreadId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 🛡️ 門禁系統：畫面載入時檢查登入狀態
  useEffect(() => {
    const sessionUser = sessionStorage.getItem("agent_user");
    if (!sessionUser) {
      router.push("/login"); // 沒登入就踢走
      return;
    }

    const user = JSON.parse(sessionUser);
    setCurrentUser(user);
    startNewChat(user); // 取得身分後，初始化房間與歡迎詞
  }, [router]);

  // 自動捲動到最底端
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 🔄 開啟新對話
  const startNewChat = (user: {name: string, email: string}) => {
    setThreadId(`frontend-ticket-${Date.now()}`);
    setMessages([
      {
        id: Date.now().toString(),
        role: "agent",
        content: `您好，**${user.name}**！我是企業 IT 維運助理。已與底層 LangGraph 狀態機與 MCP 工具鏈連線。\n\n當前授權信箱：\`${user.email}\`\n\n請問今天需要什麼協助？`,
      }
    ]);
    setInput("");
  };

  // 🚪 登出功能
  const handleLogout = () => {
    sessionStorage.removeItem("agent_user");
    router.push("/login");
  };

  // 傳送訊息 (包含 SSE 串流解析)
  const sendMessage = async (text: string, actionType: "chat" | "approve" | "reject" = "chat") => {
  if (!text.trim() && actionType === "chat") return;

  // 1. 建立使用者訊息（若是核准/駁回，可自訂提示文字）
  const userMsgText = actionType === "chat" 
    ? text 
    : actionType === "approve" ? "👍 [操作已核准，送交執行]" : "❌ [操作已駁回]";

  const userMessage: Message = {
    id: Date.now().toString(),
    role: "user",
    content: userMsgText,
  };

  // 2. 建立 Agent 的初始串流節點（預設狀態為初始化大腦）
  const agentMessageId = (Date.now() + 1).toString();
  const initialAgentMessage: Message = {
    id: agentMessageId,
    role: "agent",
    content: "",
    statusText: "🧠 大腦正在接收請求...", // 👈 真實狀態文字
    isStreaming: true,
  };

  // 更新訊息列表並開啟讀取狀態
  setMessages((prev) => [...prev, userMessage, initialAgentMessage]);
  setInput("");
  setIsLoading(true);

  try {
    // 3. 發起跨網域串流請求
    const response = await fetch("http://127.0.0.1:8000/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId || "demo-thread", // 確保有 Thread ID 綁定
        message: text,
        email: currentUser?.email || "",
        action: actionType,
      }),
    });

    if (!response.body) {
      throw new Error("後端未回傳可讀取的資料串流 (ReadableStream)。");
    }

    // 4. 開啟企業級串流閱讀器
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = ""; // 行緩衝區，防止 SSE 斷包導致 JSON 解析出錯

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      // 將二進位 Byte 轉回 UTF-8 字串並併入緩衝區
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      
      // 保留最後一行未完結的碎片
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;

        try {
          // 擷取 data: 之後的純 JSON 字串
          const rawJson = trimmed.slice(6);
          const event = JSON.parse(rawJson);

          // 🚦 5. 根據後端定義的 type 進行漸進式 UI 更新
          switch (event.type) {
            case "status":
              // 軌道 A：更新 Agent 當前正在執行的真實工具或節點
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === agentMessageId ? { ...msg, statusText: event.content } : msg
                )
              );
              break;

            case "token":
              // 軌道 B：打字機效果，將文字一個字一個字追加到對話框中
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === agentMessageId ? { ...msg, content: msg.content + event.content } : msg
                )
              );
              break;

            case "suspend":
              // 觸發安全海關：系統被 LangGraph 強制凍結，顯示審批按鈕
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === agentMessageId
                    ? { ...msg, isSuspended: true, statusText: "⏳ 觸發零信任防線：等待主管核准中" }
                    : msg
                )
              );
              break;

            case "finish":
              // 正常結束安全流程
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === agentMessageId ? { ...msg, isStreaming: false, statusText: "" } : msg
                )
              );
              break;

            case "error":
              // 捕獲例外並呈現在對話中
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === agentMessageId
                    ? { ...msg, content: msg.content + `\n\n❌ 系統異常: ${event.content}`, isStreaming: false }
                    : msg
                )
              );
              break;
          }
        } catch (err) {
          console.error("SSE 訊號行解析失敗:", trimmed, err);
        }
      }
    }
  } catch (error) {
    console.error("連線發送失敗:", error);
    // 發生連線崩潰時的安全降級
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === agentMessageId
          ? { ...msg, content: "❌ 無法連線至 IT 維運後端微服務，請確認後端 API 是否正常運作。", isStreaming: false, statusText: "" }
          : msg
      )
    );
  } finally {
    setIsLoading(false);
  }
};

  // 畫面尚未驗證身分前，不渲染內容避免閃爍
  if (!currentUser) return null; 

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* 頂部標題列與個人控制面板 */}
      <header className="bg-white shadow-sm px-6 py-4 flex items-center justify-between border-b border-gray-200 z-10">
        <div className="flex items-center gap-3">
          <Bot className="w-6 h-6 text-blue-600" />
          <h1 className="text-xl font-bold text-gray-800 tracking-tight">
            企業級 ITOps Agent <span className="text-sm font-normal text-gray-500 ml-2 hidden sm:inline-block">支援 HITL 審批攔截</span>
          </h1>
        </div>
        
        {/* 右側控制面板 */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200 text-sm font-medium text-gray-700">
            <User className="w-4 h-4 text-blue-500" />
            <span>{currentUser.name}</span>
          </div>
          
          <button 
            onClick={() => startNewChat(currentUser)}
            className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-blue-600 transition-colors px-2 py-1"
          >
            <RefreshCw className="w-4 h-4" />
            <span>新對話</span>
          </button>

          <button 
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-sm font-medium text-red-500 hover:text-red-700 transition-colors px-2 py-1 border-l border-gray-200 pl-4"
          >
            <LogOut className="w-4 h-4" />
            <span>登出</span>
          </button>
        </div>
      </header>

      {/* 訊息顯示區 */}
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 ${msg.role === "user" ? "bg-gray-800" : "bg-blue-100"}`}>
                {msg.role === "user" ? <User className="w-5 h-5 text-white" /> : <Bot className="w-5 h-5 text-blue-600" />}
              </div>
              <div className={`p-4 rounded-2xl shadow-sm max-w-[80%] ${
                msg.role === "user" 
                  ? "bg-gray-800 text-white rounded-tr-none" 
                  : msg.isSuspended 
                    ? "bg-amber-50 border-2 border-amber-200 rounded-tl-none" 
                    : "bg-white border border-gray-100 rounded-tl-none text-gray-800"
              }`}>
                {msg.role === "agent" && msg.statusText && (
                    <div className="flex items-center gap-2 text-xs font-medium text-blue-700 bg-blue-50 px-3 py-2 rounded-lg border border-blue-100 mb-2.5 animate-pulse w-fit shadow-sm">
                      <RefreshCw className="w-3.5 h-3.5 text-blue-500 animate-spin" />
                      <span>{msg.statusText}</span>
                    </div>
                  )}
                <div className="prose prose-sm max-w-none leading-relaxed prose-p:my-1 prose-strong:text-blue-700">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
                {msg.isSuspended && (
                  <div className="mt-4 flex gap-3 pt-3 border-t border-amber-200">
                    <button 
                      onClick={() => sendMessage("✅ 我已了解風險，授權系統放行操作。", "approve")}
                      className="flex items-center gap-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm"
                    >
                      <CheckCircle className="w-4 h-4" /> 授權放行
                    </button>
                    <button 
                      onClick={() => sendMessage("❌ 操作已被駁回，請取消任務。", "reject")}
                      className="flex items-center gap-1 bg-red-50 text-red-600 hover:bg-red-100 px-4 py-2 rounded-lg text-sm font-medium transition-colors border border-red-200"
                    >
                      <XCircle className="w-4 h-4" /> 駁回操作
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* 底部輸入區 */}
      <footer className="bg-white border-t border-gray-200 p-4 pb-8 z-10 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
        <div className="max-w-4xl mx-auto relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
            placeholder="請輸入您的維運需求... (按 Enter 發送)"
            disabled={isLoading}
            className="w-full pl-4 pr-12 py-4 rounded-xl border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent shadow-sm text-gray-800 bg-gray-50 focus:bg-white transition-colors disabled:opacity-50"
          />
          <button 
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50 disabled:hover:bg-blue-600"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </footer>
    </div>
  );
}