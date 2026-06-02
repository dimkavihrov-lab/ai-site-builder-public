import os
import re
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from passlib.hash import bcrypt

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
    password_hash = bcrypt.hash(req.password)
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
    if not user or not bcrypt.verify(req.password, user["password_hash"]):
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
    if not user or not bcrypt.verify(req.user_password, user["password_hash"]):
        return {"error": "Неверный email или пароль"}
    if not user["is_superuser"] and user["generations_used"] >= FREE_LIMIT:
        return {"error": f"Лимит исчерпан ({FREE_LIMIT} генераций). Ждите обновлений!"}
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": "Ты генератор HTML-шаблонов. Создай КРАСИВЫЙ адаптивный HTML-шаблон с Tailwind CSS (CDN). Базовые секции (меню, контакты, описание), без лишних функций. Изображения — placeholder.com. Все ссылки неактивны. Градиенты, тени, анимации. Отвечай ТОЛЬКО HTML в ```html ...```."
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

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>SiteForge — Генератор HTML-шаблонов</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            #preview-frame { width: 100%; height: 70vh; border: none; border-radius: 12px; display: none; background: white; }
            #preview-container { display: none; margin-top: 20px; animation: fadeIn 0.3s ease; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            .spinner { animation: spin 1s linear infinite; width: 30px; height: 30px; border: 3px solid rgba(255,255,255,0.2); border-top-color: #8b5cf6; border-radius: 50%; display: none; margin: 10px auto; }
            .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 12px; border-radius: 12px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; text-align: center; }
            .btn-primary:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(99,102,241,0.4); }
            .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
            .nav-btn { flex: 1; padding: 10px; border-radius: 10px 10px 0 0; cursor: pointer; border: none; font-size: 14px; font-weight: bold; transition: all 0.2s; }
            .nav-btn.active { background: #8b5cf6; color: white; }
            .nav-btn.inactive { background: #1e1b4b; color: #888; }
            .input-field { width: 100%; padding: 12px; border-radius: 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; font-size: 14px; outline: none; margin-bottom: 12px; }
            .input-field:focus { border-color: #8b5cf6; }
            .site-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px; margin-bottom: 8px; cursor: pointer; }
            .site-card:hover { background: rgba(255,255,255,0.1); }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; }
            .modal.active { display: flex; }
            .modal-content { background: #0f0d2e; border-radius: 16px; padding: 24px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); color: #d1d5db; }
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6 relative">
            <div class="absolute top-4 right-4 flex gap-2">
                <button onclick="openModal('help')" class="text-gray-500 hover:text-gray-300 text-xs transition">Помощь</button>
                <button onclick="openModal('about')" class="text-gray-500 hover:text-gray-300 text-xs transition">О нас</button>
            </div>
            <div class="text-center mb-6">
                <div class="text-5xl mb-2">🚀</div>
                <h1 class="text-3xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1>
                <p class="text-gray-400 mt-1 text-sm">Генератор HTML-шаблонов с помощью ИИ</p>
                <p id="user-info" class="text-xs text-gray-500 mt-1"></p>
            </div>
            <div class="flex mb-0">
                <button class="nav-btn active" id="nav-generate" onclick="switchTab('generate')">✨ Генерация</button>
                <button class="nav-btn inactive" id="nav-auth" onclick="switchTab('auth')">👤 Вход / Регистрация</button>
            </div>
            <div class="bg-white/5 backdrop-blur-lg rounded-b-2xl rounded-tr-2xl p-5 border border-white/10 shadow-2xl">
                <div id="panel-generate">
                    <input id="desc" type="text" placeholder="💡 Опиши шаблон, например: лендинг для кофейни" class="input-field" maxlength="500">
                    <button id="generateBtn" onclick="generate()" class="w-full p-4 btn-primary text-lg">✨ Создать шаблон</button>
                </div>
                <div id="panel-auth" style="display:none;">
                    <div id="auth-form-login">
                        <h3 class="text-sm font-bold mb-3">Вход</h3>
                        <input id="login-email" type="email" placeholder="Email" class="input-field">
                        <input id="login-password" type="password" placeholder="Пароль" class="input-field">
                        <button onclick="login()" class="w-full p-3 btn-primary text-sm mb-2">Войти</button>
                        <p class="text-xs text-gray-400 text-center">Нет аккаунта? <a href="#" onclick="showRegister(); return false;" class="text-white font-bold hover:underline">Зарегистрироваться</a></p>
                    </div>
                    <div id="auth-form-register" style="display:none;">
                        <h3 class="text-sm font-bold mb-3">Регистрация</h3>
                        <input id="reg-email" type="email" placeholder="Email" class="input-field">
                        <input id="reg-password" type="password" placeholder="Пароль" class="input-field">
                        <input id="reg-password2" type="password" placeholder="Подтвердите пароль" class="input-field">
                        <button onclick="register()" class="w-full p-3 btn-primary text-sm font-bold">Зарегистрироваться</button>
                        <p class="text-xs text-gray-400 text-center mt-2">Уже есть аккаунт? <a href="#" onclick="showLogin(); return false;" class="text-white font-bold hover:underline">Войти</a></p>
                    </div>
                    <p id="auth-status" class="mt-3 text-xs text-center text-gray-400"></p>
                </div>
                <div class="spinner" id="spinner"></div>
                <p id="status" class="mt-3 text-gray-400 text-xs text-center"></p>
            </div>
            <div id="preview-container">
                <div class="flex justify-between items-center mb-2 flex-wrap gap-2">
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
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-bold">📂 Мои шаблоны</h2>
                    <button onclick="clearGallery()" class="text-xs text-gray-500 hover:text-red-400">Очистить</button>
                </div>
                <div id="gallery-list"></div>
            </div>
            <div class="text-center mt-4">
                <button onclick="toggleGallery()" class="text-sm text-gray-400 hover:text-white transition" id="gallery-toggle">📂 Сохранённые шаблоны</button>
            </div>
            <div class="text-center mt-6 pb-6">
                <p class="text-xs text-gray-500">📱 Скоро в Google Play — SiteForge</p>
            </div>
        </div>
        <div id="help-modal" class="modal">
            <div class="modal-content">
                <div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">Как пользоваться</h2><button onclick="closeModal('help')" class="text-gray-500 hover:text-red-400 text-xl leading-none transition">✕</button></div>
                <div class="text-sm space-y-2"><p><strong>1.</strong> Зарегистрируйся или войди.</p><p><strong>2.</strong> Опиши шаблон.</p><p><strong>3.</strong> Нажми «Создать шаблон».</p><p><strong>4.</strong> Сохрани, скачай или скопируй HTML-код.</p></div>
            </div>
        </div>
        <div id="about-modal" class="modal">
            <div class="modal-content">
                <div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">О нас</h2><button onclick="closeModal('about')" class="text-gray-500 hover:text-red-400 text-xl leading-none transition">✕</button></div>
                <div class="text-sm space-y-2"><p><strong>SiteForge</strong> — генератор HTML-шаблонов с помощью ИИ.</p><p>Создаём красивые адаптивные заготовки за секунды.</p><p class="text-gray-400 mt-3">Версия: 1.0</p><p class="text-gray-400">Сделано с ❤️</p></div>
            </div>
        </div>
       <script>
    let currentHtml = '';
    let isGenerating = false;
    let currentUser = JSON.parse(localStorage.getItem('siteforge_user') || 'null');
    let gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
    let galleryVisible = 4;
    const FREE_LIMIT = 3;
    
    function updateUserInfo() {
        const info = document.getElementById('user-info');
        if (currentUser) {
            const left = FREE_LIMIT - currentUser.generations_used;
            info.textContent = `👤 ${currentUser.email} | Осталось: ${left > 0 ? left : 0}`;
            document.getElementById('nav-auth').textContent = '👤 Профиль';
        } else {
            info.textContent = '';
            document.getElementById('nav-auth').textContent = '👤 Вход / Регистрация';
        }
    }
    updateUserInfo();
    
    function switchTab(tab) {
        document.getElementById('panel-generate').style.display = tab === 'generate' ? 'block' : 'none';
        document.getElementById('panel-auth').style.display = tab === 'auth' ? 'block' : 'none';
        document.getElementById('nav-generate').className = tab === 'generate' ? 'nav-btn active' : 'nav-btn inactive';
        document.getElementById('nav-auth').className = tab === 'auth' ? 'nav-btn active' : 'nav-btn inactive';
        if (tab === 'auth') showLogin();
    }
    
    function showLogin() {
        document.getElementById('auth-form-login').style.display = 'block';
        document.getElementById('auth-form-register').style.display = 'none';
        document.getElementById('auth-status').textContent = '';
    }
    
    function showRegister() {
        document.getElementById('auth-form-login').style.display = 'none';
        document.getElementById('auth-form-register').style.display = 'block';
        document.getElementById('auth-status').textContent = '';
    }
    
    async function login() {
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        const status = document.getElementById('auth-status');
        if (!email || !password) { status.textContent = 'Заполни все поля'; return; }
        try {
            const res = await fetch('/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            if (!res.ok) {
                const err = await res.json();
                status.textContent = '❌ ' + err.detail;
            } else {
                const user = await res.json();
                currentUser = user;
                localStorage.setItem('siteforge_user', JSON.stringify(user));
                localStorage.setItem('siteforge_pass', password);
                status.textContent = '✅ Вход выполнен!';
                updateUserInfo();
                setTimeout(() => switchTab('generate'), 1000);
            }
        } catch(e) {
            status.textContent = '❌ Ошибка: ' + e.message;
        }
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
            const res = await fetch('/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            if (!res.ok) {
                const err = await res.json();
                status.textContent = '❌ ' + err.detail;
            } else {
                status.textContent = '✅ Регистрация успешна! Теперь войди.';
                showLogin();
                document.getElementById('login-email').value = email;
            }
        } catch(e) {
            status.textContent = '❌ Ошибка: ' + e.message;
        }
    }
    
    function generate() {
        if (isGenerating) return;
        if (!currentUser) {
            document.getElementById('status').textContent = '❌ Сначала войдите или зарегистрируйтесь!';
            switchTab('auth');
            return;
        }
        const desc = document.getElementById('desc').value;
        const status = document.getElementById('status');
        const frame = document.getElementById('preview-frame');
        const container = document.getElementById('preview-container');
        const btn = document.getElementById('generateBtn');
        const spinner = document.getElementById('spinner');
        if (!desc) { status.textContent = 'Введи описание!'; return; }
        if (!currentUser.is_superuser && currentUser.generations_used >= FREE_LIMIT) {
            status.textContent = '🔒 Лимит исчерпан. Ждите обновлений!';
            return;
        }
        isGenerating = true;
        btn.disabled = true;
        spinner.style.display = 'block';
        status.textContent = '⚡ Генерирую...';
        fetch('/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description: desc,
                email: currentUser.email,
                user_password: localStorage.getItem('siteforge_pass') || ''
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                status.textContent = '❌ ' + data.error;
            } else {
                if (!currentUser.is_superuser) {
                    currentUser.generations_used++;
                    localStorage.setItem('siteforge_user', JSON.stringify(currentUser));
                }
                currentHtml = data.html;
                frame.style.display = 'block';
                container.style.display = 'block';
                frame.srcdoc = data.html;
                status.textContent = '✅ Готово!';
                updateUserInfo();
            }
        })
        .catch(e => { status.textContent = '❌ Ошибка: ' + e.message; })
        .finally(() => {
            isGenerating = false;
            btn.disabled = false;
            spinner.style.display = 'none';
        });
    }
    
    function saveToGallery() {
        if (!currentHtml) { alert('Сначала создай шаблон!'); return; }
        const title = document.getElementById('desc').value || 'Без названия';
        gallery.unshift({ title: title, html: currentHtml, date: new Date().toLocaleString() });
        if (gallery.length > 50) gallery = gallery.slice(0, 50);
        localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
        renderGallery();
        alert('Сохранено!');
    }
    
    function renderGallery() {
        const list = document.getElementById('gallery-list');
        const visible = gallery.slice(0, galleryVisible);
        list.innerHTML = visible.map((site, i) => `
            <div class="site-card" onclick="loadFromGallery(${i})">
                <div class="flex justify-between items-center">
                    <div>
                        <span class="text-sm font-medium">${site.title}</span>
                        <span class="text-xs text-gray-500 ml-2">${site.date}</span>
                    </div>
                    <button onclick="event.stopPropagation(); deleteFromGallery(${i})" class="text-red-400 text-xs hover:text-red-300">Удалить</button>
                </div>
            </div>
        `).join('');
        if (gallery.length > 4 && galleryVisible === 4) {
            list.innerHTML += `<button onclick="showAll()" class="w-full text-center text-sm text-purple-400 hover:text-purple-300 py-2">Показать все (${gallery.length})</button>`;
        }
        if (!gallery.length) list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">Пока пусто</p>';
    }
    
    function showAll() { galleryVisible = gallery.length; renderGallery(); }
    
    function loadFromGallery(index) {
        const s = gallery[index];
        currentHtml = s.html;
        document.getElementById('desc').value = s.title;
        const f = document.getElementById('preview-frame');
        f.srcdoc = s.html;
        f.style.display = 'block';
        document.getElementById('preview-container').style.display = 'block';
    }
    
    function deleteFromGallery(index) {
        if (confirm('Удалить?')) {
            gallery.splice(index, 1);
            localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
            renderGallery();
        }
    }
    
    function clearGallery() {
        if (confirm('Удалить ВСЁ?')) {
            gallery = [];
            localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
            renderGallery();
        }
    }
    
    function toggleGallery() {
        const s = document.getElementById('gallery-section');
        const b = document.getElementById('gallery-toggle');
        if (s.style.display === 'block') {
            s.style.display = 'none';
            b.textContent = '📂 Сохранённые шаблоны';
        } else {
            s.style.display = 'block';
            b.textContent = '📂 Скрыть шаблоны';
            galleryVisible = 4;
            renderGallery();
        }
    }
    
    function copyCode() {
        if (!currentHtml) { alert('Сначала создай шаблон!'); return; }
        navigator.clipboard.writeText(currentHtml).then(() => alert('Скопировано!'));
    }
    
    function downloadHTML() {
        if (!currentHtml) { alert('Сначала создай шаблон!'); return; }
        const b = new Blob([currentHtml], {type: 'text/html'});
        const u = URL.createObjectURL(b);
        const a = document.createElement('a');
        a.href = u;
        a.download = 'шаблон.html';
        a.click();
        URL.revokeObjectURL(u);
    }
    
    function closePreview() {
        document.getElementById('preview-frame').style.display = 'none';
        document.getElementById('preview-container').style.display = 'none';
        currentHtml = '';
    }
    
    function openModal(t) { document.getElementById(t + '-modal').classList.add('active'); }
    function closeModal(t) { document.getElementById(t + '-modal').classList.remove('active'); }
    window.onclick = function(e) { if (e.target.classList.contains('modal')) e.target.classList.remove('active'); }
    
    renderGallery();
</script>
    </body>
    </html>
    """