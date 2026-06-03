import os
import re
import psycopg2
import psycopg2.extras
import bcrypt
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("PROXYAPI_KEY"),
    base_url="https://api.proxyapi.ru/openai/v1"
)

app = FastAPI()

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
            generations_used INTEGER DEFAULT 0,
            is_superuser BOOLEAN DEFAULT FALSE,
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
    cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id", (req.email, password_hash))
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Регистрация успешна", "user_id": user_id}

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
        return {"error": f"Лимит исчерпан ({FREE_LIMIT} генераций). Ждите обновлений!"}
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": (
                "Ты генератор HTML-шаблонов. Создай КРАСИВЫЙ адаптивный HTML-шаблон с Tailwind CSS (CDN). "
                "Базовые секции (меню, контакты, описание), без лишних функций. "
                "Изображения — placeholder.com или серый div. Все ссылки неактивны. "
                "Используй красивые градиенты, тени, анимации. Отвечай ТОЛЬКО HTML в ```html ...```."
            )
        }, {
            "role": "user",
            "content": f"Создай шаблон: {req.description}"
        }],
        temperature=0.8,
        max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()
    html = raw.split("```html")[1].split("```")[0].strip() if "```html" in raw else raw.split("```")[1].split("```")[0].strip() if "```" in raw else raw
    html = re.sub(r'href="[^"]*"', 'href="#"', html)
    html = re.sub(r"href='[^']*'", "href='#'", html)
    html = re.sub(r'action="[^"]*"', 'action="#"', html)
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

HEADER = """
<div class="flex justify-between items-center mb-6">
    <a href="/" class="text-gray-400 hover:text-white transition text-sm">← Назад</a>
    <div class="flex items-center gap-3" id="top-bar"></div>
</div>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>SiteForge — Генератор</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            #preview-frame {{ width: 100%; height: 70vh; border: none; border-radius: 12px; display: none; background: transparent; }}
            #preview-container {{ display: none; margin-top: 20px; animation: fadeIn 0.3s ease; }}
            @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
            @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
            .spinner {{ animation: spin 1s linear infinite; width: 30px; height: 30px; border: 3px solid rgba(255,255,255,0.2); border-top-color: #8b5cf6; border-radius: 50%; display: none; margin: 10px auto; }}
            .btn-primary {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 14px; border-radius: 14px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; text-align: center; }}
            .btn-primary:hover:not(:disabled) {{ transform: translateY(-2px); box-shadow: 0 10px 30px rgba(99,102,241,0.4); }}
            .btn-primary:disabled {{ opacity: 0.5; cursor: not-allowed; }}
            .input-field {{ width: 100%; padding: 14px; border-radius: 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; font-size: 15px; outline: none; margin-bottom: 16px; }}
            .input-field:focus {{ border-color: #8b5cf6; box-shadow: 0 0 0 2px rgba(139,92,246,0.3); }}
            .site-card {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 14px; margin-bottom: 8px; cursor: pointer; }}
            .site-card:hover {{ background: rgba(255,255,255,0.06); }}
            .avatar {{ width: 32px; height: 32px; border-radius: 50%; background: #8b5cf6; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; cursor: pointer; transition: all 0.2s; }}
            .avatar:hover {{ transform: scale(1.1); }}
            .top-avatar-wrapper {{ display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.3); border-radius: 20px; padding: 4px 10px 4px 4px; }}
            .top-email {{ font-size: 12px; color: #9ca3af; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6">
            <div class="flex justify-between items-center mb-6">
                <div class="flex gap-2">
                    <a href="/" class="text-xs text-gray-500 hover:text-gray-300 transition">Генератор</a>
                    <a href="/profile" class="text-xs text-gray-500 hover:text-gray-300 transition">Профиль</a>
                    <a href="/auth" class="text-xs text-gray-500 hover:text-gray-300 transition">Вход</a>
                </div>
                <div class="flex items-center gap-2" id="top-bar">
                    <span id="balance-display" class="text-xs text-gray-400"></span>
                    <a href="/auth" id="top-auth-link" class="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg transition font-medium">Войти</a>
                    <a href="/profile" id="top-avatar-link" style="display:none;">
                        <div class="top-avatar-wrapper">
                            <div class="avatar" id="avatar-icon"></div>
                            <span class="top-email" id="avatar-email"></span>
                        </div>
                    </a>
                </div>
            </div>
            
            <div class="text-center mb-8">
                <div class="text-5xl mb-2">🚀</div>
                <h1 class="text-4xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1>
                <p class="text-gray-400 mt-2 text-sm">Создай HTML-шаблон за секунды</p>
            </div>
            
            <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10 shadow-2xl">
                <input id="desc" type="text" placeholder="💡 Опиши шаблон, например: лендинг для кофейни" class="input-field" maxlength="500">
                <button id="generateBtn" onclick="generate()" class="w-full p-4 btn-primary text-lg">✨ Создать шаблон</button>
                <div class="spinner" id="spinner"></div>
                <p id="status" class="mt-4 text-gray-400 text-xs text-center"></p>
            </div>
            
            <div id="preview-container">
                <div class="flex justify-between items-center mb-3 flex-wrap gap-2">
                    <span class="text-sm text-gray-300">Предпросмотр</span>
                    <div class="flex gap-1 flex-wrap">
                        <button onclick="saveToGallery()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">💾</button>
                        <button onclick="downloadHTML()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">📥</button>
                        <button onclick="copyCode()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">📋</button>
                        <button onclick="closePreview()" class="text-gray-500 hover:text-red-400 text-lg px-2 leading-none transition">✕</button>
                    </div>
                </div>
                <iframe id="preview-frame"></iframe>
            </div>
            
            <div id="gallery-section" style="display:none; margin-top: 30px;">
                <div class="flex justify-between items-center mb-4"><h2 class="text-lg font-bold">📂 Мои шаблоны</h2><button onclick="clearGallery()" class="text-xs text-gray-500 hover:text-red-400">Очистить</button></div>
                <div id="gallery-list"></div>
            </div>
            <div class="text-center mt-4"><button onclick="toggleGallery()" class="text-sm text-gray-400 hover:text-white transition" id="gallery-toggle">📂 Сохранённые шаблоны</button></div>
        </div>
        
        <script>
            let currentHtml = '';
            let isGenerating = false;
            let currentUser = JSON.parse(localStorage.getItem('siteforge_user') || 'null');
            let gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
            let galleryVisible = 4;
            const FREE_LIMIT = 3;
            
            function updateTopBar() {{
                const balance = document.getElementById('balance-display');
                const authLink = document.getElementById('top-auth-link');
                const avatarLink = document.getElementById('top-avatar-link');
                const avatarIcon = document.getElementById('avatar-icon');
                const avatarEmail = document.getElementById('avatar-email');
                if (currentUser) {{
                    const left = currentUser.is_superuser ? '∞' : Math.max(0, FREE_LIMIT - currentUser.generations_used);
                    balance.textContent = 'Баланс: ' + left + ' ген.';
                    authLink.style.display = 'none';
                    avatarLink.style.display = 'block';
                    avatarIcon.textContent = currentUser.email.charAt(0).toUpperCase();
                    avatarEmail.textContent = currentUser.email.split('@')[0];
                }} else {{
                    balance.textContent = '';
                    authLink.style.display = 'block';
                    avatarLink.style.display = 'none';
                }}
            }}
            updateTopBar();
            
            function generate() {{
                if (isGenerating) return;
                if (!currentUser) {{ document.getElementById('status').textContent = '❌ Сначала войдите!'; window.location.href='/auth'; return; }}
                const desc = document.getElementById('desc').value;
                const status = document.getElementById('status');
                const frame = document.getElementById('preview-frame');
                const container = document.getElementById('preview-container');
                const btn = document.getElementById('generateBtn');
                const spinner = document.getElementById('spinner');
                if (!desc) {{ status.textContent = 'Введи описание!'; return; }}
                if (!currentUser.is_superuser && currentUser.generations_used >= FREE_LIMIT) {{ status.textContent = '🔒 Лимит исчерпан.'; return; }}
                isGenerating = true; btn.disabled = true; spinner.style.display = 'block'; status.textContent = '⚡ Генерирую...';
                fetch('/generate', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ description: desc, email: currentUser.email, user_password: localStorage.getItem('siteforge_pass') || '' }}) }})
                .then(res => res.json())
                .then(data => {{
                    if (data.error) {{ status.textContent = '❌ ' + data.error; }}
                    else {{
                        if (!currentUser.is_superuser) {{ currentUser.generations_used++; localStorage.setItem('siteforge_user', JSON.stringify(currentUser)); }}
                        currentHtml = data.html; frame.style.display = 'block'; container.style.display = 'block'; frame.srcdoc = data.html;
                        status.textContent = '✅ Готово!'; updateTopBar();
                    }}
                }})
                .catch(e => {{ status.textContent = '❌ Ошибка: ' + e.message; }})
                .finally(() => {{ isGenerating = false; btn.disabled = false; spinner.style.display = 'none'; }});
            }}
            
            function saveToGallery() {{ if (!currentHtml) {{ alert('Сначала создай шаблон!'); return; }} const title = document.getElementById('desc').value || 'Без названия'; gallery.unshift({{ title, html: currentHtml, date: new Date().toLocaleString() }}); if (gallery.length > 50) gallery = gallery.slice(0, 50); localStorage.setItem('siteforge_gallery', JSON.stringify(gallery)); renderGallery(); alert('Сохранено!'); }}
            function renderGallery() {{ const list = document.getElementById('gallery-list'); const visible = gallery.slice(0, galleryVisible); list.innerHTML = visible.map((s, i) => `<div class="site-card" onclick="loadFromGallery(${{i}})"><div class="flex justify-between items-center"><div><span class="text-sm font-medium">${{s.title}}</span><span class="text-xs text-gray-500 ml-2">${{s.date}}</span></div><button onclick="event.stopPropagation(); deleteFromGallery(${{i}})" class="text-red-400 text-xs hover:text-red-300">Удалить</button></div></div>`).join(''); if (gallery.length > 4 && galleryVisible === 4) list.innerHTML += `<button onclick="showAll()" class="w-full text-center text-sm text-purple-400 hover:text-purple-300 py-2">Показать все (${{gallery.length}})</button>`; if (!gallery.length) list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">Пока пусто</p>'; }}
            function showAll() {{ galleryVisible = gallery.length; renderGallery(); }}
            function loadFromGallery(i) {{ const s = gallery[i]; currentHtml = s.html; document.getElementById('desc').value = s.title; const f = document.getElementById('preview-frame'); f.srcdoc = s.html; f.style.display = 'block'; document.getElementById('preview-container').style.display = 'block'; }}
            function deleteFromGallery(i) {{ if (confirm('Удалить?')) {{ gallery.splice(i, 1); localStorage.setItem('siteforge_gallery', JSON.stringify(gallery)); renderGallery(); }} }}
            function clearGallery() {{ if (confirm('Удалить ВСЁ?')) {{ gallery = []; localStorage.setItem('siteforge_gallery', JSON.stringify(gallery)); renderGallery(); }} }}
            function toggleGallery() {{ const s = document.getElementById('gallery-section'), b = document.getElementById('gallery-toggle'); if (s.style.display === 'block') {{ s.style.display = 'none'; b.textContent = '📂 Сохранённые шаблоны'; }} else {{ s.style.display = 'block'; b.textContent = '📂 Скрыть шаблоны'; galleryVisible = 4; renderGallery(); }} }}
            function copyCode() {{ if (!currentHtml) {{ alert('Сначала создай шаблон!'); return; }} navigator.clipboard.writeText(currentHtml).then(() => alert('Скопировано!')); }}
            function downloadHTML() {{ if (!currentHtml) {{ alert('Сначала создай шаблон!'); return; }} const b = new Blob([currentHtml], {{type: 'text/html'}}); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = 'шаблон.html'; a.click(); URL.revokeObjectURL(u); }}
            function closePreview() {{ document.getElementById('preview-frame').style.display = 'none'; document.getElementById('preview-container').style.display = 'none'; currentHtml = ''; }}
            renderGallery();
        </script>
    </body>
    </html>
    """

@app.get("/profile", response_class=HTMLResponse)
def profile_page():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SiteForge — Профиль</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .package-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; text-align: center; transition: all 0.2s; }
            .package-card:hover { border-color: #8b5cf6; background: rgba(139,92,246,0.08); }
            .package-card.popular { border-color: #f59e0b; background: rgba(245,158,11,0.05); }
            .btn-buy { background: #8b5cf6; color: white; padding: 10px 24px; border-radius: 10px; font-size: 14px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; opacity: 0.5; }
            .btn-buy:hover { background: #7c3aed; }
            .avatar-large { width: 64px; height: 64px; border-radius: 50%; background: #8b5cf6; display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: bold; margin: 0 auto; }
        </style>
    </head>
    <body class="bg-gray-950 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6">
            <div class="flex justify-between items-center mb-6">
                <a href="/" class="text-gray-400 hover:text-white transition text-sm">← Назад к генератору</a>
                <div class="flex gap-2">
                    <a href="/" class="text-xs text-gray-500 hover:text-gray-300">Генератор</a>
                    <a href="/auth" class="text-xs text-gray-500 hover:text-gray-300">Вход</a>
                </div>
            </div>
            
            <div id="profile-content" class="bg-gray-900 rounded-2xl p-8 border border-gray-800">
                <div id="profile-logged-out">
                    <p class="text-center text-gray-400">Войдите, чтобы увидеть профиль.</p>
                    <div class="text-center mt-4"><a href="/auth" class="text-purple-400 hover:underline text-sm">Войти</a></div>
                </div>
                <div id="profile-logged-in" style="display:none;">
                    <div class="avatar-large mb-4" id="profile-avatar"></div>
                    <h2 class="text-xl font-bold text-center mb-1" id="profile-email"></h2>
                    <p class="text-center text-3xl font-bold mb-2" id="profile-balance"></p>
                    <div class="w-16 mx-auto border-b-2 border-purple-500 mb-6"></div>
                    <p class="text-center text-gray-400 text-sm mb-6">Пакеты генераций</p>
                    <div class="grid grid-cols-2 gap-3">
                        <div class="package-card"><h3 class="text-lg font-bold">10 ген.</h3><p class="text-2xl font-bold my-2">150₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card"><h3 class="text-lg font-bold">25 ген.</h3><p class="text-2xl font-bold my-2">300₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card popular"><h3 class="text-lg font-bold">50 ген.</h3><p class="text-2xl font-bold my-2">600₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card"><h3 class="text-lg font-bold">100 ген.</h3><p class="text-2xl font-bold my-2">1000₽</p><button class="btn-buy" disabled>Скоро</button></div>
                    </div>
                </div>
            </div>
        </div>
        <script>
            const user = JSON.parse(localStorage.getItem('siteforge_user') || 'null');
            if (user) {
                document.getElementById('profile-logged-out').style.display = 'none';
                document.getElementById('profile-logged-in').style.display = 'block';
                document.getElementById('profile-avatar').textContent = user.email.charAt(0).toUpperCase();
                document.getElementById('profile-email').textContent = user.email;
                const left = user.is_superuser ? '∞' : Math.max(0, 3 - user.generations_used);
                document.getElementById('profile-balance').textContent = left + ' ген.';
            }
        </script>
    </body>
    </html>
    """

@app.get("/auth", response_class=HTMLResponse)
def auth_page():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SiteForge — Вход</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .input-field { width: 100%; padding: 14px; border-radius: 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; font-size: 15px; outline: none; margin-bottom: 16px; }
            .input-field:focus { border-color: #8b5cf6; }
            .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 14px; border-radius: 14px; font-weight: bold; cursor: pointer; border: none; width: 100%; }
            .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(99,102,241,0.4); }
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-md w-full px-4 mx-auto py-12">
            <div class="flex justify-between items-center mb-6">
                <a href="/" class="text-gray-400 hover:text-white transition text-sm">← Назад</a>
            </div>
            <div class="text-center mb-8"><div class="text-5xl mb-2">🚀</div><h1 class="text-2xl font-bold">Вход / Регистрация</h1></div>
            <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10">
                <div id="auth-form-login">
                    <h3 class="text-sm font-bold mb-4">Вход</h3>
                    <input id="login-email" type="email" placeholder="Email" class="input-field">
                    <input id="login-password" type="password" placeholder="Пароль" class="input-field">
                    <button onclick="login()" class="btn-primary mb-3">Войти</button>
                    <p class="text-xs text-gray-400 text-center">Нет аккаунта? <a href="#" onclick="showRegister(); return false;" class="text-white font-bold hover:underline">Зарегистрироваться</a></p>
                </div>
                <div id="auth-form-register" style="display:none;">
                    <h3 class="text-sm font-bold mb-4">Регистрация</h3>
                    <input id="reg-email" type="email" placeholder="Email" class="input-field">
                    <input id="reg-password" type="password" placeholder="Пароль" class="input-field">
                    <input id="reg-password2" type="password" placeholder="Подтвердите пароль" class="input-field">
                    <button onclick="register()" class="btn-primary mb-3">Зарегистрироваться</button>
                    <p class="text-xs text-gray-400 text-center">Уже есть аккаунт? <a href="#" onclick="showLogin(); return false;" class="text-white font-bold hover:underline">Войти</a></p>
                </div>
                <p id="auth-status" class="mt-3 text-xs text-center text-gray-400"></p>
            </div>
        </div>
        <script>
            function showLogin() { document.getElementById('auth-form-login').style.display = 'block'; document.getElementById('auth-form-register').style.display = 'none'; document.getElementById('auth-status').textContent = ''; }
            function showRegister() { document.getElementById('auth-form-login').style.display = 'none'; document.getElementById('auth-form-register').style.display = 'block'; document.getElementById('auth-status').textContent = ''; }
            async function login() {
                const email = document.getElementById('login-email').value;
                const password = document.getElementById('login-password').value;
                const status = document.getElementById('auth-status');
                if (!email || !password) { status.textContent = 'Заполни все поля'; return; }
                try {
                    const res = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
                    if (!res.ok) { const err = await res.json(); status.textContent = '❌ ' + err.detail; }
                    else {
                        const user = await res.json();
                        localStorage.setItem('siteforge_user', JSON.stringify(user));
                        localStorage.setItem('siteforge_pass', password);
                        status.textContent = '✅ Вход выполнен!';
                        setTimeout(() => { window.location.href = '/'; }, 1000);
                    }
                } catch(e) { status.textContent = '❌ Ошибка: ' + e.message; }
            }
            async function register() {
                const email = document.getElementById('reg-email').value;
                const password = document.getElementById('reg-password').value;
                const password2 = document.getElementById('reg-password2').value;
                const status = document.getElementById('auth-status');
                if (!email || !password || !password2) { status.textContent = 'Заполни все поля'; return; }
                if (password !== password2) { status.textContent = '❌ Пароли не совпадают'; return; }
                if (password.length < 4) { status.textContent = '❌ Пароль должен быть не менее 4 символов'; return; }
                try {
                    const res = await fetch('/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
                    if (!res.ok) { const err = await res.json(); status.textContent = '❌ ' + err.detail; }
                    else { status.textContent = '✅ Регистрация успешна! Теперь войди.'; showLogin(); document.getElementById('login-email').value = email; }
                } catch(e) { status.textContent = '❌ Ошибка: ' + e.message; }
            }
        </script>
    </body>
    </html>
    """