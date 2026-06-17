"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";

// 定義訊息的資料結構
type Message = {
  id: string;
  role: "user" | "agent";
  content: string;
  isSuspended?: boolean;
};

// 寫死 Bob 的身分與一個獨立的 Thread ID 供 POC 測試使用
const POC_USER_EMAIL = "bob.lee@globaltech.com";

export default function Home() {
  const [threadId] = useState(() => `frontend-ticket-${Date.now()}`);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-msg",
      role: "agent",
      content: "您好，Bob Lee！我是企業 IT 維運助理。已與底層 LangGraph 狀態機與 MCP 工具鏈連線。\n\n請問今天需要什麼協助？（您可以嘗試向我申請安裝 **Navicat** 軟體）",
    }
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 當有新訊息時，自動捲動到最底端
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 發送訊息到 FastAPI 後端
  // 新增 action 參數，預設為 "chat"
  const sendMessage = async (text: string, action: "chat" | "approve" | "reject" = "chat") => {
    if (!text.trim() || isLoading) return;

    // 1. 先把使用者的訊息加到畫面上
    const newUserMsg: Message = { id: Date.now().toString(), role: "user", content: text };
    setMessages((prev) => [...prev, newUserMsg]);
    setInput("");
    setIsLoading(true);

    try {
      // 2. 呼叫我們自己寫的 FastAPI
      const res = await fetch("http://127.0.0.1:8000/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId, 
          message: text,
          email: POC_USER_EMAIL,
          action: action,
        }),
      });

      if (!res.ok) throw new Error("伺服器連線失敗");
      const data = await res.json();

      // 3. 把 Agent 的回覆加到畫面上
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: "agent",
          content: data.response,
          isSuspended: data.is_suspended, // 紀錄這則訊息是否觸發了 HITL 攔截
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { id: Date.now().toString(), role: "agent", content: "❌ 連線到後端發生錯誤，請確認 FastAPI 伺服器是否運行中。" }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* 頂部標題列 */}
      <header className="bg-white shadow-sm px-6 py-4 flex items-center gap-3 border-b border-gray-200 z-10">
        <Bot className="w-6 h-6 text-blue-600" />
        <h1 className="text-xl font-bold text-gray-800 tracking-tight">
          企業級 ITOps Agent <span className="text-sm font-normal text-gray-500 ml-2">支援 HITL 審批攔截</span>
        </h1>
      </header>

      {/* 訊息顯示區 */}
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
              
              {/* 大頭貼 */}
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 ${msg.role === "user" ? "bg-gray-800" : "bg-blue-100"}`}>
                {msg.role === "user" ? <User className="w-5 h-5 text-white" /> : <Bot className="w-5 h-5 text-blue-600" />}
              </div>

              {/* 訊息對話框 */}
              <div className={`p-4 rounded-2xl shadow-sm max-w-[80%] ${
                msg.role === "user" 
                  ? "bg-gray-800 text-white rounded-tr-none" 
                  : msg.isSuspended 
                    ? "bg-amber-50 border-2 border-amber-200 rounded-tl-none" // 攔截狀態的特殊樣式
                    : "bg-white border border-gray-100 rounded-tl-none text-gray-800"
              }`}>
                {/* 如果是被凍結的狀態，顯示動態核准按鈕 */}
                {msg.isSuspended && (
                  <div className="mt-4 flex gap-3">
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
                
                {/* 渲染 Markdown 內容 */}
                <div className="prose prose-sm max-w-none leading-relaxed prose-p:my-1 prose-strong:text-blue-700">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>

                {/* 如果是被凍結的狀態，顯示動態核准按鈕 */}
                {msg.isSuspended && (
                  <div className="mt-4 flex gap-3">
                    <button 
                      onClick={() => sendMessage("我已了解風險，這是我本人授權的，請解鎖並強制執行！")}
                      className="flex items-center gap-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm"
                    >
                      <CheckCircle className="w-4 h-4" /> 授權放行
                    </button>
                    <button 
                      onClick={() => sendMessage("取消此次操作。")}
                      className="flex items-center gap-1 bg-red-50 text-red-600 hover:bg-red-100 px-4 py-2 rounded-lg text-sm font-medium transition-colors border border-red-200"
                    >
                      <XCircle className="w-4 h-4" /> 駁回操作
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* 打字中 Loading 動畫 */}
          {isLoading && (
            <div className="flex gap-4">
              <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0 mt-1">
                <Bot className="w-5 h-5 text-blue-600" />
              </div>
              <div className="bg-white p-4 rounded-2xl rounded-tl-none shadow-sm border border-gray-100 flex items-center gap-2 text-gray-500 text-sm">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                  <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "0.4s" }}></div>
                </div>
                <span>Agent 正在檢索 SOP 與處理工單...</span>
              </div>
            </div>
          )}
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