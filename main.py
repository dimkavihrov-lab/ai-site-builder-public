import os
import re
import secrets
import psycopg2
import psycopg2.extras
import bcrypt
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("PROXYAPI_KEY"),
    base_url="https://api.proxyapi.ru/openai/v1"
)

app = FastAPI()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL", "https://ai-site-builder-public-production.up.railway.app")

def send_telegram_code(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text})
    except:
        pass

def get_db():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        db_host = os.getenv("PGHOST")
        db_port = os.getenv("PGPORT", "5432")
        db_name = os.getenv("PGDATABASE", "railway")
        db_user = os.getenv("PGUSER", "postgres")
        db_password = os.getenv("PGPASSWORD")
        if db_host and db_password:
            database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        else:
            raise Exception("DATABASE_URL or PGHOST/PGPASSWORD not set")
    return psycopg2.connect(database_url)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            telegram_chat_id BIGINT,
            generations_used INTEGER DEFAULT 0,
            is_superuser BOOLEAN DEFAULT FALSE,
            email_verified BOOLEAN DEFAULT FALSE,
            verification_code VARCHAR(6),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

last_site = {"html": ""}
FREE_LIMIT = 3

class SiteRequest(BaseModel):
    description: str
    email: str
    user_password: str

class EditRequest(BaseModel):
    html: str
    old_text: str
    new_text: str

class AuthRequest(BaseModel):
    email: str
    password: str

class VerifyCodeRequest(BaseModel):
    email: str
    code: str

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        
        if not chat_id or not text:
            return {"ok": True}
        
        if text.startswith("/start"):
            send_telegram_code(chat_id, "👋 Привет! Отправь /code твой-email чтобы получить код подтверждения.")
        elif text.startswith("/code"):
            parts = text.split()
            if len(parts) >= 2:
                email = parts[1]
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT verification_code, email_verified FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
                if row and not row[1]:  # не подтверждён
                    send_telegram_code(chat_id, f"🔐 Твой код подтверждения: {row[0]}")
                elif row and row[1]:
                    send_telegram_code(chat_id, "✅ Этот email уже подтверждён.")
                else:
                    send_telegram_code(chat_id, "❌ Email не найден. Сначала зарегистрируйся на сайте.")
                cur.close()
                conn.close()
            else:
                send_telegram_code(chat_id, "Используй: /code твой-email@example.com")
    except:
        pass
    return {"ok": True}

@app.post("/verify-code")
def verify_code(req: VerifyCodeRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT verification_code FROM users WHERE email = %s AND email_verified = FALSE", (req.email,))
    row = cur.fetchone()
    if row and row[0] == req.code:
        cur.execute("UPDATE users SET email_verified = TRUE, verification_code = NULL WHERE email = %s", (req.email,))
        conn.commit()
        cur.close()
        conn.close()
        return {"message": "Email подтверждён"}
    cur.close()
    conn.close()
    raise HTTPException(status_code=400, detail="Неверный код")

@app.post("/register")
def register(req: AuthRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    
    password_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    code = secrets.token_hex(3).upper()[:6]
    
    cur.execute(
        "INSERT INTO users (email, password_hash, verification_code) VALUES (%s, %s, %s) RETURNING id",
        (req.email, password_hash, code)
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return {"message": f"Регистрация успешна. Напишите боту @siteforge_verify_bot команду /code {req.email}", "code": code}

@app.post("/login")
def login(req: AuthRequest):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user or not bcrypt.checkpw(req.password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if not user["email_verified"]:
        raise HTTPException(status_code=403, detail="Email не подтверждён. Напишите боту @siteforge_verify_bot /code ваш-email")
    return {"email": user["email"], "generations_used": user["generations_used"], "is_superuser": user["is_superuser"]}

@app.post("/edit")
def edit_html(req: EditRequest):
    return {"html": req.html.replace(req.old_text, req.new_text)}

@app.post("/generate")
def generate_site(req: SiteRequest):
    global last_site
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user or not bcrypt.checkpw(req.user_password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        return {"error": "Неверный email или пароль"}
    if not user["is_superuser"] and user["generations_used"] >= FREE_LIMIT:
        return {"error": f"Лимит исчерпан ({FREE_LIMIT} генераций)."}
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": (
                "Ты генератор HTML-шаблонов. Создай КРАСИВЫЙ адаптивный HTML-шаблон с Tailwind CSS (CDN). "
                "Базовые секции (меню, контакты, описание), без лишних функций. "
                "Изображения — placeholder.com. Все ссылки неактивны. "
                "Градиенты, тени, анимации. Отвечай ТОЛЬКО HTML в ```html ...```."
            )
        }, {"role": "user", "content": f"Создай шаблон: {req.description}"}],
        temperature=0.8, max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()
    html = raw.split("```html")[1].split("```")[0].strip() if "```html" in raw else raw.split("```")[1].split("```")[0].strip() if "```" in raw else raw
    html = re.sub(r'href="[^"]*"', 'href="#"', html)
    html = re.sub(r"href='[^']*'", "href='#'", html)
    html = html.replace('</head>', '<style>a{text-decoration:none!important;pointer-events:none;cursor:default;color:inherit}</style></head>')

    if not user["is_superuser"]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET generations_used = generations_used + 1 WHERE id = %s", (user["id"],))
        conn.commit()
        cur.close()
        conn.close()

    last_site["html"] = html
    return {"html": html}

@app.get("/view", response_class=HTMLResponse)
def view_site():
    return last_site["html"]

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SiteForge</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
    <script src="https://cdn.tailwindcss.com"></script><style>
    #preview-frame{width:100%;height:70vh;border:none;border-radius:12px;display:none;background:transparent}
    #preview-container{display:none;margin-top:20px;animation:fadeIn 0.3s}
    @keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
    @keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
    .spinner{animation:spin 1s linear infinite;width:30px;height:30px;border:3px solid rgba(255,255,255,0.2);border-top-color:#8b5cf6;border-radius:50%;display:none;margin:10px auto}
    .btn-primary{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;padding:14px;border-radius:14px;font-weight:bold;cursor:pointer;border:none}
    .input-field{width:100%;padding:14px;border-radius:14px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:white;font-size:15px;outline:none;margin-bottom:16px}
    .input-field:focus{border-color:#8b5cf6}
    .site-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:14px;margin-bottom:8px;cursor:pointer}
    .avatar{width:32px;height:32px;border-radius:50%;background:#8b5cf6;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:bold}
    .top-avatar-wrapper{display:flex;align-items:center;gap:8px;background:rgba(0,0,0,0.3);border-radius:20px;padding:4px 10px 4px 4px}
    .top-email{font-size:12px;color:#9ca3af;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:100;align-items:center;justify-content:center}
    .modal.active{display:flex}
    .modal-content{background:#0f0d2e;border-radius:16px;padding:24px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto;border:1px solid rgba(255,255,255,0.1);color:#d1d5db}
    </style></head><body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
    <div class="max-w-2xl w-full px-4 mx-auto py-6">
    <div class="flex justify-between items-center mb-6"><div class="flex gap-2"><button onclick="openModal('help')" class="text-xs text-gray-500 hover:text-gray-300">Помощь</button><button onclick="openModal('about')" class="text-xs text-gray-500 hover:text-gray-300">О нас</button></div>
    <div class="flex items-center gap-3"><span id="balance-display" class="text-sm text-white font-bold"></span><a href="/auth" id="top-auth-link" class="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg font-medium">Войти</a><a href="/profile" id="top-avatar-link" style="display:none"><div class="top-avatar-wrapper"><div class="avatar" id="avatar-icon"></div><span class="top-email" id="avatar-email"></span></div></a></div></div>
    <div class="text-center mb-8"><div class="text-5xl mb-2">🚀</div><h1 class="text-4xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1><p class="text-gray-400 mt-2 text-sm">Создай HTML-шаблон за секунды</p></div>
    <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10"><input id="desc" type="text" placeholder="💡 Опиши шаблон" class="input-field" maxlength="500"><button id="generateBtn" onclick="generate()" class="w-full p-4 btn-primary text-lg">✨ Создать шаблон</button><div class="spinner" id="spinner"></div><p id="status" class="mt-4 text-gray-400 text-xs text-center"></p></div>
    <div id="preview-container"><div class="flex justify-between items-center mb-3 flex-wrap gap-2"><span class="text-sm text-gray-300">Предпросмотр</span><div class="flex gap-1"><button onclick="saveToGallery()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg">💾</button><button onclick="downloadHTML()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg">📥</button><button onclick="copyCode()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg">📋</button><button onclick="closePreview()" class="text-gray-500 hover:text-red-400 text-lg px-2">✕</button></div></div><iframe id="preview-frame"></iframe></div>
    <div id="gallery-section" style="display:none;margin-top:30px"><div class="flex justify-between items-center mb-4"><h2 class="text-lg font-bold">📂 Мои шаблоны</h2><button onclick="clearGallery()" class="text-xs text-gray-500 hover:text-red-400">Очистить</button></div><div id="gallery-list"></div></div>
    <div class="text-center mt-4"><button onclick="toggleGallery()" class="text-sm text-gray-400 hover:text-white">📂 Сохранённые шаблоны</button></div></div>
    <div id="help-modal" class="modal"><div class="modal-content"><div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">Как пользоваться</h2><button onclick="closeModal('help')" class="text-gray-500 hover:text-red-400 text-xl">✕</button></div><div class="text-sm space-y-2"><p><strong>1.</strong> Зарегистрируйся.</p><p><strong>2.</strong> Напиши боту @siteforge_verify_bot /code твой-email</p><p><strong>3.</strong> Введи код на странице входа.</p><p><strong>4.</strong> Создавай шаблоны!</p></div></div></div>
    <div id="about-modal" class="modal"><div class="modal-content"><div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">О нас</h2><button onclick="closeModal('about')" class="text-gray-500 hover:text-red-400 text-xl">✕</button></div><div class="text-sm space-y-2"><p><strong>SiteForge</strong> — генератор HTML-шаблонов с помощью ИИ.</p><p class="text-gray-400 mt-3">Версия: 1.0 | Сделано с ❤️</p></div></div></div>
    <script>
    let currentHtml='',isGenerating=false,currentUser=JSON.parse(localStorage.getItem('siteforge_user')||'null'),gallery=JSON.parse(localStorage.getItem('siteforge_gallery')||'[]'),galleryVisible=4;
    function updateTopBar(){const b=document.getElementById('balance-display'),a=document.getElementById('top-auth-link'),l=document.getElementById('top-avatar-link'),i=document.getElementById('avatar-icon'),e=document.getElementById('avatar-email');if(currentUser){const left=currentUser.is_superuser?'∞':Math.max(0,3-currentUser.generations_used);b.textContent='Баланс: '+left+' ген.';a.style.display='none';l.style.display='block';i.textContent=currentUser.email.charAt(0).toUpperCase();e.textContent=currentUser.email.split('@')[0]}else{b.textContent='';a.style.display='block';l.style.display='none'}}updateTopBar();
    function generate(){if(isGenerating)return;if(!currentUser){document.getElementById('status').textContent='❌ Сначала войдите!';window.location.href='/auth';return}const d=document.getElementById('desc').value,s=document.getElementById('status'),f=document.getElementById('preview-frame'),c=document.getElementById('preview-container'),btn=document.getElementById('generateBtn'),sp=document.getElementById('spinner');if(!d){s.textContent='Введи описание!';return}if(!currentUser.is_superuser&&currentUser.generations_used>=3){s.textContent='🔒 Лимит исчерпан.';return}isGenerating=true;btn.disabled=true;sp.style.display='block';s.textContent='⚡ Генерирую...';fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description:d,email:currentUser.email,user_password:localStorage.getItem('siteforge_pass')||''})}).then(r=>r.json()).then(data=>{if(data.error){s.textContent='❌ '+data.error}else{if(!currentUser.is_superuser){currentUser.generations_used++;localStorage.setItem('siteforge_user',JSON.stringify(currentUser))}currentHtml=data.html;f.style.display='block';c.style.display='block';f.srcdoc=data.html;s.textContent='✅ Готово!';updateTopBar()}}).catch(e=>{s.textContent='❌ Ошибка: '+e.message}).finally(()=>{isGenerating=false;btn.disabled=false;sp.style.display='none'})}
    function saveToGallery(){if(!currentHtml){alert('Сначала создай шаблон!');return}gallery.unshift({title:document.getElementById('desc').value||'Без названия',html:currentHtml,date:new Date().toLocaleString()});if(gallery.length>50)gallery=gallery.slice(0,50);localStorage.setItem('siteforge_gallery',JSON.stringify(gallery));renderGallery();alert('Сохранено!')}
    function renderGallery(){const list=document.getElementById('gallery-list'),visible=gallery.slice(0,galleryVisible);list.innerHTML=visible.map((s,i)=>`<div class="site-card" onclick="loadFromGallery(${i})"><div class="flex justify-between items-center"><div><span class="text-sm font-medium">${s.title}</span><span class="text-xs text-gray-500 ml-2">${s.date}</span></div><button onclick="event.stopPropagation();deleteFromGallery(${i})" class="text-red-400 text-xs">Удалить</button></div></div>`).join('');if(gallery.length>4&&galleryVisible===4)list.innerHTML+=`<button onclick="showAll()" class="w-full text-center text-sm text-purple-400 py-2">Показать все (${gallery.length})</button>`;if(!gallery.length)list.innerHTML='<p class="text-gray-500 text-sm text-center py-4">Пока пусто</p>'}
    function showAll(){galleryVisible=gallery.length;renderGallery()}
    function loadFromGallery(i){const s=gallery[i];currentHtml=s.html;document.getElementById('desc').value=s.title;const f=document.getElementById('preview-frame');f.srcdoc=s.html;f.style.display='block';document.getElementById('preview-container').style.display='block'}
    function deleteFromGallery(i){if(confirm('Удалить?')){gallery.splice(i,1);localStorage.setItem('siteforge_gallery',JSON.stringify(gallery));renderGallery()}}
    function clearGallery(){if(confirm('Удалить ВСЁ?')){gallery=[];localStorage.setItem('siteforge_gallery',JSON.stringify(gallery));renderGallery()}}
    function toggleGallery(){const s=document.getElementById('gallery-section'),b=document.getElementById('gallery-toggle');if(s.style.display==='block'){s.style.display='none';b.textContent='📂 Сохранённые шаблоны'}else{s.style.display='block';b.textContent='📂 Скрыть шаблоны';galleryVisible=4;renderGallery()}}
    function copyCode(){if(!currentHtml){alert('Сначала создай шаблон!');return}navigator.clipboard.writeText(currentHtml).then(()=>alert('Скопировано!'))}
    function downloadHTML(){if(!currentHtml){alert('Сначала создай шаблон!');return}const b=new Blob([currentHtml],{type:'text/html'}),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='шаблон.html';a.click();URL.revokeObjectURL(u)}
    function closePreview(){document.getElementById('preview-frame').style.display='none';document.getElementById('preview-container').style.display='none';currentHtml=''}
    function openModal(t){document.getElementById(t+'-modal').classList.add('active')}
    function closeModal(t){document.getElementById(t+'-modal').classList.remove('active')}
    window.onclick=function(e){if(e.target.classList.contains('modal'))e.target.classList.remove('active')}
    renderGallery();
    </script></body></html>"""

@app.get("/profile", response_class=HTMLResponse)
def profile_page():
    return """
    <!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SiteForge — Профиль</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
    <script src="https://cdn.tailwindcss.com"></script><style>
    .package-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:24px;text-align:center}
    .package-card.popular{border-color:#f59e0b}
    .btn-buy{background:#8b5cf6;color:white;padding:10px 24px;border-radius:10px;font-size:14px;font-weight:bold;border:none;opacity:0.5}
    .avatar-large{width:64px;height:64px;border-radius:50%;background:#8b5cf6;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:bold;margin:0 auto}
    </style></head><body class="bg-gray-950 text-white min-h-screen">
    <div class="max-w-2xl w-full px-4 mx-auto py-6"><a href="/" class="text-gray-400 hover:text-white text-sm">← Назад</a>
    <div class="bg-gray-900 rounded-2xl p-8 border border-gray-800 mt-4 relative">
    <div id="plo"><p class="text-center text-gray-400">Войдите. <a href="/auth" class="text-purple-400">Войти</a></p></div>
    <div id="pli" style="display:none"><div class="avatar-large mb-4" id="pa"></div><h2 class="text-xl font-bold text-center mb-1" id="pe"></h2>
    <p class="text-center text-3xl font-bold mb-2" id="pb"></p><div class="w-16 mx-auto border-b-2 border-purple-500 mb-6"></div>
    <p class="text-center text-gray-400 text-sm mb-6">Пакеты генераций</p>
    <div class="grid grid-cols-2 gap-3">
    <div class="package-card"><h3 class="text-lg font-bold">10 ген.</h3><p class="text-2xl font-bold my-2">150₽</p><button class="btn-buy" disabled>Скоро</button></div>
    <div class="package-card"><h3 class="text-lg font-bold">25 ген.</h3><p class="text-2xl font-bold my-2">300₽</p><button class="btn-buy" disabled>Скоро</button></div>
    <div class="package-card popular"><h3 class="text-lg font-bold">50 ген.</h3><p class="text-2xl font-bold my-2">600₽</p><button class="btn-buy" disabled>Скоро</button></div>
    <div class="package-card"><h3 class="text-lg font-bold">100 ген.</h3><p class="text-2xl font-bold my-2">1000₽</p><button class="btn-buy" disabled>Скоро</button></div></div>
    <button onclick="logout()" class="absolute bottom-6 right-6 text-red-400 hover:text-red-300 text-sm">Выйти</button></div></div></div>
    <script>
    const u=JSON.parse(localStorage.getItem('siteforge_user')||'null');
    if(u){document.getElementById('plo').style.display='none';document.getElementById('pli').style.display='block';document.getElementById('pa').textContent=u.email.charAt(0).toUpperCase();document.getElementById('pe').textContent=u.email;document.getElementById('pb').textContent=(u.is_superuser?'∞':Math.max(0,3-u.generations_used))+' ген.'}
    function logout(){localStorage.removeItem('siteforge_user');localStorage.removeItem('siteforge_pass');window.location.href='/'}
    </script></body></html>"""

@app.get("/auth", response_class=HTMLResponse)
def auth_page():
    return """
    <!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SiteForge — Вход</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
    <script src="https://cdn.tailwindcss.com"></script><style>
    .input-field{width:100%;padding:14px;border-radius:14px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:white;font-size:15px;outline:none;margin-bottom:16px}
    .input-field:focus{border-color:#8b5cf6}
    .btn-primary{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;padding:14px;border-radius:14px;font-weight:bold;border:none;width:100%}
    </style></head><body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
    <div class="max-w-md w-full px-4 mx-auto py-12"><a href="/" class="text-gray-400 hover:text-white text-sm">← Назад</a>
    <div class="text-center mb-8 mt-4"><div class="text-5xl mb-2">🚀</div><h1 class="text-2xl font-bold">Вход / Регистрация</h1></div>
    <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10">
    <div id="afl"><h3 class="text-sm font-bold mb-4">Вход</h3><input id="le" type="email" placeholder="Email" class="input-field"><input id="lp" type="password" placeholder="Пароль" class="input-field"><button onclick="login()" class="btn-primary mb-3">Войти</button><p class="text-xs text-gray-400 text-center">Нет аккаунта? <a href="#" onclick="showReg()" class="text-white font-bold hover:underline">Зарегистрироваться</a></p></div>
    <div id="afr" style="display:none"><h3 class="text-sm font-bold mb-4">Регистрация</h3><input id="re" type="email" placeholder="Email" class="input-field"><input id="rp" type="password" placeholder="Пароль" class="input-field"><input id="rp2" type="password" placeholder="Подтвердите пароль" class="input-field"><button onclick="register()" class="btn-primary mb-3">Зарегистрироваться</button><p class="text-xs text-gray-400 text-center">Уже есть аккаунт? <a href="#" onclick="showLog()" class="text-white font-bold hover:underline">Войти</a></p></div>
    <p id="as" class="mt-3 text-xs text-center text-gray-400"></p></div></div>
    <script>
    function showLog(){document.getElementById('afl').style.display='block';document.getElementById('afr').style.display='none';document.getElementById('as').textContent=''}
    function showReg(){document.getElementById('afl').style.display='none';document.getElementById('afr').style.display='block';document.getElementById('as').textContent=''}
    async function login(){const e=document.getElementById('le').value,p=document.getElementById('lp').value,s=document.getElementById('as');if(!e||!p){s.textContent='Заполни все поля';return}try{const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});if(!r.ok){const d=await r.json();s.textContent='❌ '+d.detail}else{const u=await r.json();localStorage.setItem('siteforge_user',JSON.stringify(u));localStorage.setItem('siteforge_pass',p);s.textContent='✅ Вход!';setTimeout(()=>{window.location.href='/'},1000)}}catch(e){s.textContent='❌ Ошибка: '+e.message}}
    async function register(){const e=document.getElementById('re').value,p=document.getElementById('rp').value,p2=document.getElementById('rp2').value,s=document.getElementById('as');if(!e||!p||!p2){s.textContent='Заполни все поля';return}if(p!==p2){s.textContent='❌ Пароли не совпадают';return}if(p.length<4){s.textContent='❌ Пароль от 4 символов';return}try{const r=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});const d=await r.json();if(!r.ok){s.textContent='❌ '+d.detail}else{s.textContent='✅ Зарегистрирован! Напиши боту @siteforge_verify_bot /code '+e;document.getElementById('le').value=e;showLog()}}catch(e){s.textContent='❌ Ошибка: '+e.message}}
    </script></body></html>"""