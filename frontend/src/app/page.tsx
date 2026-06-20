"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Send, Bot, User, AlertTriangle, CheckCircle, XCircle, RefreshCw, LogOut, MessageSquare, PlusCircle, Menu } from "lucide-react";
import ReactMarkdown from "react-markdown";

type Message = {
  id: string;
  role: "user" | "agent";
  content: string;
  isSuspended?: boolean;
  statusText?: string;
  isStreaming?: boolean;
};

type Thread = {
  thread_id: string;
  title: string;
  updated_at: string;
};

export default function Home() {
  const router = useRouter();
  
  // 狀態管理
  const [currentUser, setCurrentUser] = useState<{name: string, email: string, role: string} | null>(null);
  const [threadId, setThreadId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  
  // 側邊欄狀態
  const [threads, setThreads] = useState<Thread[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 🛡️ 門禁系統與初始化
  useEffect(() => {
    const sessionUser = sessionStorage.getItem("agent_user");
    if (!sessionUser) {
      router.push("/login");
      return;
    }

    const user = JSON.parse(sessionUser);
    setCurrentUser(user);
    loadThreads(user.email); // 載入側邊欄對話歷史
    startNewChat(user);
  }, [router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 📥 載入歷史對話清單
  const loadThreads = async (email: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/threads?email=${email}`);
      const data = await res.json();
      if (data.status === "success") {
        setThreads(data.threads);
      }
    } catch (error) {
      console.error("無法載入對話紀錄:", error);
    }
  };

  // 🔄 開啟新對話
  const startNewChat = (user: {name: string, email: string}) => {
    const newThreadId = `chat-${Date.now()}`;
    setThreadId(newThreadId);
    setMessages([
      {
        id: Date.now().toString(),
        role: "agent",
        content: `您好，**${user.name}**！我是企業 IT 維運助理。\n\n當前授權信箱：\`${user.email}\`\n請問今天需要什麼協助？`,
      }
    ]);
    setInput("");
  };

  // 切換歷史對話房間 (目前 MVP 先單純切換 Thread ID 並清空畫面，未來可再串接撈取歷史訊息 API)
  const switchThread = (selectedThreadId: string) => {
    setThreadId(selectedThreadId);
    setMessages([
      {
        id: Date.now().toString(),
        role: "agent",
        content: `🔄 已切換至對話空間：\`${selectedThreadId}\`\n\n(提示：正在載入歷史對話上下文...)`,
      }
    ]);
  };

  const handleLogout = () => {
    sessionStorage.removeItem("agent_user");
    router.push("/login");
  };

  // 🚀 傳送訊息 (包含完整 SSE 串流)
  const sendMessage = async (text: string, actionType: "chat" | "approve" | "reject" = "chat") => {
    if (!text.trim() && actionType === "chat") return;

    const userMsgText = actionType === "chat" 
      ? text 
      : actionType === "approve" ? "✅ [操作已核准，送交執行]" : "❌ [操作已駁回]";

    const userMessage: Message = { id: Date.now().toString(), role: "user", content: userMsgText };
    const agentMessageId = (Date.now() + 1).toString();
    const initialAgentMessage: Message = {
      id: agentMessageId, role: "agent", content: "", statusText: "🧠 大腦正在接收請求...", isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, initialAgentMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch("http://127.0.0.1:8000/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          message: text,
          email: currentUser?.email || "",
          action: actionType,
        }),
      });

      if (!response.body) throw new Error("無串流回應");

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;

          try {
            const event = JSON.parse(trimmed.slice(6));

            switch (event.type) {
              case "status":
                setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, statusText: event.content } : msg));
                break;
              case "token":
                setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, content: msg.content + event.content } : msg));
                break;
              case "suspend":
                setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, isSuspended: true, statusText: "⏳ 觸發零信任防線：等待主管核准中" } : msg));
                break;
              case "finish":
                setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, isStreaming: false, statusText: "" } : msg));
                // 執行完畢後偷偷刷新側邊欄，看看有沒有新的系統通知
                if (currentUser) loadThreads(currentUser.email);
                break;
              case "error":
                setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, content: msg.content + `\n\n❌ 系統異常: ${event.content}`, isStreaming: false, statusText: "" } : msg));
                break;
            }
          } catch (err) {
            console.error("解析失敗:", trimmed, err);
          }
        }
      }
    } catch (error) {
      setMessages((prev) => prev.map((msg) => msg.id === agentMessageId ? { ...msg, content: "❌ 無法連線至 IT 維運後端。", isStreaming: false, statusText: "" } : msg));
    } finally {
      setIsLoading(false);
    }
  };

  if (!currentUser) return null;

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      
      {/* 🟢 左側邊欄 (Sidebar) */}
      <aside className={`${isSidebarOpen ? "w-72" : "w-0"} transition-all duration-300 bg-gray-900 flex flex-col overflow-hidden shrink-0 shadow-xl z-20 relative`}>
        <div className="p-4 flex items-center justify-between border-b border-gray-800">
          <h2 className="text-white font-bold text-lg flex items-center gap-2 tracking-wide">
            <Bot className="w-5 h-5 text-blue-400" /> ITOps Agent
          </h2>
        </div>
        
        <div className="p-3">
          <button 
            onClick={() => startNewChat(currentUser)}
            className="w-full flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm"
          >
            <PlusCircle className="w-4 h-4" /> 建立新維運需求
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1 custom-scrollbar">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 px-2 mt-2">近期對話紀錄</div>
          {threads.map((thread) => (
            <button 
              key={thread.thread_id}
              onClick={() => switchThread(thread.thread_id)}
              className={`w-full flex flex-col text-left px-3 py-2.5 rounded-lg transition-colors group ${
                threadId === thread.thread_id ? "bg-gray-800 border border-gray-700" : "hover:bg-gray-800 border border-transparent"
              }`}
            >
              <div className="flex items-center gap-2 text-sm text-gray-200">
                <MessageSquare className={`w-4 h-4 shrink-0 ${thread.title.includes("系統通知") ? "text-amber-400" : "text-gray-400"}`} />
                <span className="truncate font-medium">{thread.title}</span>
              </div>
              <span className="text-[11px] text-gray-500 pl-6 mt-1">{thread.updated_at}</span>
            </button>
          ))}
          {threads.length === 0 && (
            <div className="text-sm text-gray-500 text-center mt-6">尚無對話紀錄</div>
          )}
        </div>

        <div className="p-4 border-t border-gray-800 bg-gray-900/50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center border border-gray-700">
                <User className="w-4 h-4 text-gray-300" />
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-medium text-gray-200 leading-tight">{currentUser.name}</span>
                <span className="text-xs text-gray-500">{currentUser.role === "admin" ? "IT 主管 (Admin)" : "一般員工"}</span>
              </div>
            </div>
            <button onClick={handleLogout} className="text-gray-500 hover:text-red-400 p-1.5 transition-colors">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* 🔵 右側主要對話區 */}
      <main className="flex-1 flex flex-col h-full w-full relative">
        <header className="bg-white/80 backdrop-blur-md shadow-sm px-4 py-3 flex items-center justify-between border-b border-gray-200 absolute top-0 w-full z-10">
          <div className="flex items-center gap-3">
            <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} className="p-1.5 text-gray-500 hover:text-gray-800 bg-gray-100 rounded-md transition-colors">
              <Menu className="w-5 h-5" />
            </button>
            <h1 className="text-lg font-bold text-gray-800 tracking-tight">維運對話空間</h1>
          </div>
          <div className="text-xs font-mono bg-blue-50 text-blue-600 px-3 py-1 rounded-full border border-blue-100">
            Thread ID: {threadId.substring(0, 15)}...
          </div>
        </header>

        {/* 訊息顯示區 */}
        <div className="flex-1 overflow-y-auto p-6 pt-20 custom-scrollbar pb-24">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex gap-4 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 shadow-sm ${msg.role === "user" ? "bg-gray-800" : "bg-blue-600"}`}>
                  {msg.role === "user" ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-white" />}
                </div>
                <div className={`px-5 py-3.5 rounded-2xl shadow-sm leading-relaxed text-[15px] max-w-[85%] ${
                  msg.role === "user" 
                    ? "bg-gray-800 text-white rounded-tr-none" 
                    : msg.isSuspended 
                      ? "bg-amber-50 border border-amber-200 rounded-tl-none text-gray-800" 
                      : "bg-white border border-gray-200 rounded-tl-none text-gray-800"
                }`}>
                  {msg.role === "agent" && msg.statusText && (
                    <div className="flex items-center gap-2 text-[13px] font-medium text-blue-700 bg-blue-50 px-3 py-2 rounded-lg border border-blue-100 mb-3 w-fit shadow-sm">
                      <RefreshCw className="w-3.5 h-3.5 text-blue-500 animate-spin" />
                      <span>{msg.statusText}</span>
                    </div>
                  )}
                  <div className="prose prose-sm max-w-none prose-p:my-1 prose-strong:text-blue-700">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                  {msg.isSuspended && (
                    <div className="mt-4 flex gap-3 pt-3 border-t border-amber-200">
                      {currentUser?.role === "admin" ? (
                        <>
                          <button onClick={() => sendMessage("✅ 我已了解風險，授權系統放行操作。", "approve")} className="flex items-center gap-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm">
                            <CheckCircle className="w-4 h-4" /> 主管核准
                          </button>
                          <button onClick={() => sendMessage("❌ 操作已被駁回，請取消任務。", "reject")} className="flex items-center gap-1 bg-white text-red-600 hover:bg-red-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors border border-red-200">
                            <XCircle className="w-4 h-4" /> 駁回
                          </button>
                        </>
                      ) : (
                        <div className="text-sm text-amber-700 font-medium flex items-center gap-2">
                          <AlertTriangle className="w-4 h-4 text-amber-500" />
                          已凍結：等待 IT 主管簽核
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* 底部輸入區 */}
        <footer className="absolute bottom-0 w-full bg-gradient-to-t from-gray-50 via-gray-50 to-transparent p-4 pt-10 z-10">
          <div className="max-w-3xl mx-auto relative bg-white rounded-xl shadow-sm border border-gray-200">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
              placeholder="請輸入您的維運需求... (按 Enter 發送)"
              disabled={isLoading}
              className="w-full pl-5 pr-14 py-4 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-800 bg-transparent disabled:opacity-50"
            />
            <button 
              onClick={() => sendMessage(input)}
              disabled={isLoading || !input.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2.5 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-40"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </footer>
      </main>
    </div>
  );
}