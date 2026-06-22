"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Send, Bot, User, AlertTriangle, CheckCircle, 
         XCircle, RefreshCw, LogOut, MessageSquare, PlusCircle, 
         Menu, MoreVertical, Pin, PinOff, Pencil, Trash2, Check } from "lucide-react";
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
  is_pinned?: boolean;
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 側邊欄進階 UI 狀態
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

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

  // 點擊畫面任意處，自動關閉下拉選單
  useEffect(() => {
    const handleClickOutside = () => setMenuOpenId(null);
    document.addEventListener("click", handleClickOutside);
    return () => document.removeEventListener("click", handleClickOutside);
  }, []);

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

  // 🔄 切換歷史對話房間並載入上下文
  const switchThread = async (selectedThreadId: string) => {
    setThreadId(selectedThreadId);
    setIsLoading(true);
    
    // 先顯示載入中的過場訊息
    setMessages([
      {
        id: "loading",
        role: "agent",
        content: `🔄 正在從伺服器載入歷史對話上下文 (\`${selectedThreadId}\`)...`,
        statusText: "撈取記憶體中..."
      }
    ]);

    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/chat/history?thread_id=${selectedThreadId}`);
      const data = await res.json();
      
      if (data.status === "success" && data.messages.length > 0) {
        // 成功撈取歷史訊息，直接覆蓋畫面
        setMessages(data.messages);
      } else {
        // 🌟🌟🌟 企業級 UX：系統通知自動觸發邏輯 🌟🌟🌟
        const match = selectedThreadId.match(/sys-notify-(INC-[A-Z0-9\-]+)/);
        
        if (match) {
          // 如果是待簽核工單的通知房，且尚未有歷史對話
          const ticketId = match[1];
          setMessages([]); // 先清空畫面過場訊息
          
          // 延遲 100ms 自動幫主管發送隱藏指令給 AI，確保 React 狀態已準備好
          setTimeout(() => {
            sendMessage(
              `【系統隱藏指令】我剛打開了工單 ${ticketId} 的審批通知。請幫我呼叫工具查詢這張工單的詳細內容、申請人是誰，以及完整的簽核關卡進度 (Approval Steps)。請整理成一份專業的「簽核摘要報告」呈現給我。`, 
              "chat", 
              selectedThreadId
            );
          }, 100);
        } else {
          // 正常的對話房沒紀錄時的預設防呆語
          setMessages([
            {
              id: Date.now().toString(),
              role: "agent",
              content: `歡迎回到對話空間：\`${selectedThreadId}\`\n\n請問有什麼我可以繼續幫忙的嗎？`,
            }
          ]);
        }
      }
    } catch (error) {
      setMessages([
        {
          id: "error",
          role: "agent",
          content: `❌ 無法連線至伺服器讀取歷史紀錄。`,
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = () => {
    sessionStorage.removeItem("agent_user");
    router.push("/login");
  };

  // 🚀 傳送訊息 (包含完整 SSE 串流)
  const sendMessage = async (text: string, actionType: "chat" | "approve" | "reject" = "chat", targetThreadId?: string) => {
    const currentThread = targetThreadId || threadId; // 確保使用正確的房間 ID

    if (!text.trim() && actionType === "chat") return;

    // 如果是點擊按鈕，立刻把畫面上所有舊按鈕消除，防止重複點擊
    if (actionType === "approve" || actionType === "reject") {
      setMessages((prev) => prev.map(msg => ({ ...msg, isSuspended: false })));
    }

    const userMsgText = actionType === "chat" 
      ? text 
      : actionType === "approve" ? "✅ [操作已確認授權]" : "❌ [操作已取消]";

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
          thread_id: currentThread,
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
        
        const events = buffer.split("\n\n"); 
        buffer = events.pop() || "";

        for (const eventStr of events) {
          const trimmed = eventStr.trim();
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

// 📌 切換釘選狀態
  const togglePin = async (threadId: string, currentPinStatus: boolean) => {
    try {
      await fetch(`http://127.0.0.1:8000/api/v1/threads/${threadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_pinned: !currentPinStatus }),
      });
      if (currentUser) loadThreads(currentUser.email);
    } catch (e) { console.error(e); }
    setMenuOpenId(null);
  };

  // ✏️ 確認重新命名
  const confirmRename = async (threadId: string) => {
    if (!editTitle.trim()) return;
    try {
      await fetch(`http://127.0.0.1:8000/api/v1/threads/${threadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: editTitle }),
      });
      if (currentUser) loadThreads(currentUser.email);
    } catch (e) { console.error(e); }
    setEditingThreadId(null);
    setMenuOpenId(null);
  };

  // 🗑️ 刪除對話
  const deleteThread = async (targetThreadId: string) => { 
    const confirmDelete = window.confirm("確定要刪除這筆對話紀錄嗎？");
    if (!confirmDelete) return;
    try {
      await fetch(`http://127.0.0.1:8000/api/v1/threads/${targetThreadId}`, { method: "DELETE" });
      if (currentUser) loadThreads(currentUser.email);
      
      // 判斷「當前畫面所在的房間 (threadId)」是否等於「被刪除的房間 (targetThreadId)」
      if (threadId === targetThreadId && currentUser) startNewChat(currentUser); 
    } catch (e) { console.error(e); }
    setMenuOpenId(null);
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
            <PlusCircle className="w-4 h-4" /> 建立新對話
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1 custom-scrollbar">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 px-2 mt-2">近期對話紀錄</div>
          
          {threads.map((thread) => (
            <div key={thread.thread_id} className="relative group">
              {editingThreadId === thread.thread_id ? (
                // ✏️ 編輯模式 UI
                <div className="w-full flex items-center bg-gray-800 px-2 py-2 rounded-lg border border-blue-500">
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && confirmRename(thread.thread_id)}
                    className="flex-1 bg-transparent text-sm text-white outline-none"
                    autoFocus
                  />
                  <button onClick={() => confirmRename(thread.thread_id)} className="p-1 text-green-400 hover:text-green-300">
                    <Check className="w-4 h-4" />
                  </button>
                  <button onClick={() => setEditingThreadId(null)} className="p-1 text-gray-400 hover:text-gray-300">
                    <XCircle className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                // 🟢 正常顯示模式 UI
                <button 
                  onClick={() => switchThread(thread.thread_id)}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg transition-colors ${
                    threadId === thread.thread_id ? "bg-gray-800 border border-gray-700" : "hover:bg-gray-800 border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-2 text-sm text-gray-200 overflow-hidden">
                    {thread.is_pinned ? (
                      <Pin className="w-4 h-4 shrink-0 text-blue-400" />
                    ) : (
                      <MessageSquare className={`w-4 h-4 shrink-0 ${thread.title.includes("系統通知") ? "text-amber-400" : "text-gray-400"}`} />
                    )}
                    <span className="truncate font-medium text-left">{thread.title}</span>
                  </div>
                  
                  {/* Hover 時才出現的「⋯」按鈕 */}
                  <div 
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-gray-700 rounded-md shrink-0"
                    onClick={(e) => {
                      e.stopPropagation(); // 阻止事件冒泡觸發 switchThread
                      setMenuOpenId(menuOpenId === thread.thread_id ? null : thread.thread_id);
                    }}
                  >
                    <MoreVertical className="w-4 h-4 text-gray-400" />
                  </div>
                </button>
              )}

              {/* 🎯 展開的下拉選單 (Dropdown Menu) */}
              {menuOpenId === thread.thread_id && (
                <div className="absolute right-2 top-10 w-36 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden py-1">
                  <button 
                    onClick={(e) => { e.stopPropagation(); togglePin(thread.thread_id, !!thread.is_pinned); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-200 hover:bg-gray-700 transition-colors"
                  >
                    {thread.is_pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
                    {thread.is_pinned ? "取消釘選" : "釘選"}
                  </button>
                  <button 
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      setEditTitle(thread.title); 
                      setEditingThreadId(thread.thread_id); 
                      setMenuOpenId(null); 
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-200 hover:bg-gray-700 transition-colors"
                  >
                    <Pencil className="w-4 h-4" /> 重新命名
                  </button>
                  <button 
                    onClick={(e) => { e.stopPropagation(); deleteThread(thread.thread_id); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-gray-700 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" /> 刪除
                  </button>
                </div>
              )}
            </div>
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
            <h1 className="text-lg font-bold text-gray-800 tracking-tight">ITOps 智能助手</h1>
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
                      {/* 拔除 role === "admin" 的判斷，按鈕呈現給當前對話者 */}
                      <button onClick={() => sendMessage("✅ 我已確認風險，授權執行此操作。", "approve")} className="flex items-center gap-1 bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm">
                        <AlertTriangle className="w-4 h-4" /> 確認授權執行
                      </button>
                      <button onClick={() => sendMessage("❌ 操作已取消。", "reject")} className="flex items-center gap-1 bg-white text-gray-600 hover:bg-gray-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors border border-gray-200">
                        <XCircle className="w-4 h-4" /> 取消操作
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
            {/* 🌟 專屬 BPM 簽核的 Quick Actions 快捷鍵 🌟 */}
            {threadId.startsWith("sys-notify-") && messages.length > 0 && !isLoading && (
              <div className="flex flex-wrap gap-3 mt-6 pt-4 border-t border-gray-200 animate-in fade-in duration-300">
                <span className="text-sm font-semibold text-gray-500 w-full mb-1">主管快捷簽核：</span>
                <button 
                  onClick={() => sendMessage("✅ 我同意核准此工單 (Approve)。請幫我執行。")} 
                  className="flex items-center gap-1.5 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm"
                >
                   <CheckCircle className="w-4 h-4" /> 核准放行
                </button>
                <button 
                  onClick={() => sendMessage("🔄 請將此工單退回給前一關的主管重新評估 (Reject Previous)。")} 
                  className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm"
                >
                   <RefreshCw className="w-4 h-4" /> 退回前一關
                </button>
                <button 
                  onClick={() => sendMessage("❌ 我拒絕此申請，請直接退回給原申請人 (Reject Applicant)。")} 
                  className="flex items-center gap-1.5 bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm transition-colors shadow-sm"
                >
                   <XCircle className="w-4 h-4" /> 退回申請人
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 底部輸入區 */}
        <footer className="absolute bottom-0 w-full bg-gradient-to-t from-gray-50 via-gray-50 to-transparent p-4 pt-10 z-10">
          <div className="max-w-3xl mx-auto relative bg-white rounded-xl shadow-sm border border-gray-200">
            <textarea
              ref={textareaRef} // 綁定 ref 到 textarea 標籤上
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                // 簡易的 Auto-resize 邏輯：讓輸入框隨文字長高，最高不超過 160px
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                // 攔截 Enter 鍵：如果是 Enter 且沒按 Shift，就送出訊息
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault(); // 阻止預設的換行行為
                  if (!isLoading && input.trim()) {
                    sendMessage(input);
                    // 改用 textareaRef 來縮回高度
                    if (textareaRef.current) textareaRef.current.style.height = 'auto';
                  }
                }
              }}
              rows={1}
              placeholder="請輸入您的維運需求... (Shift + Enter 換行，Enter 發送)"
              disabled={isLoading}
              className="w-full pl-5 pr-14 py-4 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-800 bg-transparent disabled:opacity-50 resize-none overflow-y-auto leading-relaxed"
              style={{ minHeight: '56px' }}
            />
            <button 
              onClick={() => {
                sendMessage(input);
                // 點擊發送按鈕時，也把輸入框高度縮回原狀
                if (textareaRef.current) textareaRef.current.style.height = 'auto';
              }}
              disabled={isLoading || !input.trim()}
              // 注意：這裡把 top-1/2 改成了 bottom-2，確保輸入框長高時，按鈕依然貼齊右下角
              className="absolute right-2 bottom-2 p-2.5 text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-40"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </footer>
      </main>
    </div>
  );
}