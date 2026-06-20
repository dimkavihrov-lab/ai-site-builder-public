import os
import re
import psycopg2
import psycopg2.extras
import bcrypt
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

class ChangePasswordRequest(BaseModel):
    email: str
    old_password: str
    new_password: str

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
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Регистрация успешна"}

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

@app.post("/change-password")
def change_password(req: ChangePasswordRequest):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    user = cur.fetchone()
    if not user or not bcrypt.checkpw(req.old_password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Неверный старый пароль")
    new_hash = bcrypt.hashpw(req.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cur.execute("UPDATE users SET password_hash = %s WHERE email = %s", (new_hash, req.email))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Пароль изменён"}

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
        return {"error": f"Лимит исчерпан ({FREE_LIMIT} бесплатных генераций). Приобретите пакет в профиле!"}
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": (
                "Ты генератор HTML-шаблонов. Создай КРАСИВЫЙ адаптивный HTML-шаблон с Tailwind CSS (CDN). "
                "ОБЯЗАТЕЛЬНО используй явный фон для body (например bg-gray-100, bg-white, bg-blue-50). Фон НЕ должен быть прозрачным. "
                "Базовые секции, placeholder.com для картинок, неактивные ссылки. "
                "Заголовки должны помещаться в одну строку, не обрезаться. "
                "Градиенты, тени, анимации. Отвечай ТОЛЬКО HTML в ```html ...```."
            )
        }, {"role": "user", "content": f"Создай шаблон: {req.description}"}],
        temperature=0.8, max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()
    html = raw.split("```html")[1].split("```")[0].strip() if "```html" in raw else raw.split("```")[1].split("```")[0].strip() if "```" in raw else raw

    html = re.sub(r'(<a\b[^>]*?)href="[^"]*"', r'\1href="#"', html)
    html = re.sub(r"(<a\b[^>]*?)href='[^']*'", r"\1href='#'", html)
    html = re.sub(r'action="[^"]*"', 'action="#"', html)
    
    # Принудительный фон если его нет
    if '<body' in html and 'bg-' not in html.split('<body')[1].split('>')[0]:
        html = html.replace('<body', '<body class="bg-gray-100"')
    
    html = html.replace('</head>', '<style>body{max-width:100vw!important;overflow-x:hidden!important;background:#f3f4f6!important}a{text-decoration:none!important;pointer-events:none;cursor:default;color:inherit}*{word-wrap:break-word!important;overflow-wrap:anywhere!important}</style></head>')

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
        <title>SiteForge — Генератор</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            * { word-wrap: break-word; overflow-wrap: anywhere; }
            #preview-frame { width: 100%; height: 70vh; border: none; border-radius: 12px; display: none; background: transparent; }
            #preview-container { display: none; margin-top: 20px; animation: fadeIn 0.3s ease; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            .spinner { animation: spin 1s linear infinite; width: 30px; height: 30px; border: 3px solid rgba(255,255,255,0.2); border-top-color: #8b5cf6; border-radius: 50%; display: none; margin: 10px auto; }
            .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 14px; border-radius: 14px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; text-align: center; }
            .btn-primary:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(99,102,241,0.4); }
            .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
            .input-field { width: 100%; padding: 14px; border-radius: 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; font-size: 15px; outline: none; margin-bottom: 16px; }
            .input-field:focus { border-color: #8b5cf6; box-shadow: 0 0 0 2px rgba(139,92,246,0.3); }
            .site-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 14px; margin-bottom: 8px; cursor: pointer; }
            .site-card:hover { background: rgba(255,255,255,0.06); }
            .avatar { width: 32px; height: 32px; border-radius: 50%; background: #8b5cf6; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; cursor: pointer; }
            .top-avatar-wrapper { display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.3); border-radius: 20px; padding: 4px 10px 4px 4px; }
            .top-email { font-size: 12px; color: #9ca3af; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; }
            .modal.active { display: flex; }
            .modal-content { background: #0f0d2e; border-radius: 16px; padding: 24px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); color: #d1d5db; }
            .copy-menu { position: relative; display: inline-block; }
            .copy-dropdown { display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: #1e1b4b; border-radius: 12px; padding: 8px; min-width: 180px; z-index: 50; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 4px; }
            .copy-menu.active .copy-dropdown { display: block; }
            .copy-option { display: block; width: 100%; padding: 8px 12px; text-align: left; background: none; border: none; color: #d1d5db; font-size: 13px; cursor: pointer; border-radius: 8px; }
            .copy-option:hover { background: rgba(139,92,246,0.2); color: white; }
            .edit-btn { color: #60a5fa; text-decoration: none; font-size: 13px; cursor: pointer; background: none; border: none; }
            .edit-btn:hover { color: #93c5fd; text-decoration: none; }
            .editable-hint { position: absolute; background: #8b5cf6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 10px; pointer-events: none; display: none; z-index: 200; }
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6">
            <div class="flex justify-between items-center mb-6">
                <div class="flex gap-2">
                    <button onclick="openModal('help')" class="text-xs text-gray-500 hover:text-gray-300 transition">Помощь</button>
                    <button onclick="openModal('about')" class="text-xs text-gray-500 hover:text-gray-300 transition">О нас</button>
                </div>
                <div class="flex items-center gap-3">
                    <span id="balance-display" class="text-sm text-white font-bold"></span>
                    <a href="/auth" id="top-auth-link" class="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg transition font-medium">Войти</a>
                    <a href="/profile" id="top-avatar-link" style="display:none;">
                        <div class="top-avatar-wrapper"><div class="avatar" id="avatar-icon"></div><span class="top-email" id="avatar-email"></span></div>
                    </a>
                </div>
            </div>
            <div class="text-center mb-8"><div class="text-5xl mb-2">🚀</div><h1 class="text-4xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1><p class="text-gray-400 mt-2 text-sm">Создайте HTML-шаблон за секунды</p></div>
            <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10 shadow-2xl">
                <input id="desc" type="text" placeholder="💡 Опишите шаблон, например: лендинг для кофейни" class="input-field" maxlength="500">
                <button id="generateBtn" onclick="generate()" class="w-full p-4 btn-primary text-lg">✨ Создать шаблон</button>
                <div class="spinner" id="spinner"></div><p id="status" class="mt-4 text-gray-400 text-xs text-center"></p>
            </div>
            <div id="preview-container">
                <div class="flex justify-between items-center mb-3 flex-wrap gap-2">
                    <span class="text-sm text-gray-300">Предпросмотр | <button onclick="toggleEditMode()" id="edit-mode-btn" class="edit-btn">✏️ Редактировать текст</button></span>
                    <div class="flex gap-1 flex-wrap items-center">
                        <button onclick="saveToGallery()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">💾 Сохранить</button>
                        <button onclick="downloadHTML()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">📥 Скачать</button>
                        <div class="copy-menu" id="copyMenu">
                            <button onclick="toggleCopyMenu()" class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded-lg transition">📋 Копировать ▾</button>
                            <div class="copy-dropdown">
                                <button onclick="copyCode('full')" class="copy-option">📄 Весь HTML</button>
                                <button onclick="copyCode('body')" class="copy-option">📝 Только body</button>
                                <button onclick="copyCode('css')" class="copy-option">🎨 Только стили</button>
                            </div>
                        </div>
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
        <div id="help-modal" class="modal"><div class="modal-content"><div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">Как пользоваться</h2><button onclick="closeModal('help')" class="text-gray-500 hover:text-red-400 text-xl">✕</button></div><div class="text-sm space-y-2"><p><strong>1.</strong> Зарегистрируйтесь или войдите.</p><p><strong>2.</strong> Опишите шаблон.</p><p><strong>3.</strong> Нажмите «Создать».</p><p><strong>4.</strong> Нажмите «✏️ Редактировать» и кликайте на текст.</p><p><strong>5.</strong> Скопируйте или скачайте готовый HTML.</p></div></div></div>
        <div id="about-modal" class="modal"><div class="modal-content"><div class="flex justify-between items-center mb-3"><h2 class="text-lg font-bold text-white">О нас</h2><button onclick="closeModal('about')" class="text-gray-500 hover:text-red-400 text-xl">✕</button></div><div class="text-sm space-y-2"><p><strong>SiteForge</strong> — генератор HTML-шаблонов с помощью ИИ.</p><p class="text-gray-400 mt-3">Версия: 1.2 | Сделано с ❤️</p></div></div></div>
        <div class="editable-hint" id="edit-hint">Нажмите на текст чтобы изменить</div>
        <script>
            let currentHtml = '', isGenerating = false, editMode = false;
            let currentUser = JSON.parse(localStorage.getItem('siteforge_user') || 'null');
            let gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
            let galleryVisible = 4;
            const FREE_LIMIT = 3;
            
            function updateTopBar() {
                const b = document.getElementById('balance-display'), a = document.getElementById('top-auth-link'), l = document.getElementById('top-avatar-link'), i = document.getElementById('avatar-icon'), e = document.getElementById('avatar-email');
                if (currentUser) {
                    const left = currentUser.is_superuser ? '∞' : Math.max(0, FREE_LIMIT - currentUser.generations_used);
                    b.textContent = 'Баланс: ' + left + ' ген.'; a.style.display = 'none'; l.style.display = 'block';
                    i.textContent = currentUser.email.charAt(0).toUpperCase(); e.textContent = currentUser.email.split('@')[0];
                } else { b.textContent = ''; a.style.display = 'block'; l.style.display = 'none'; }
            }
            updateTopBar();
            
            function generate() {
                if (isGenerating) return;
                if (!currentUser) { document.getElementById('status').textContent = '❌ Сначала войдите!'; window.location.href = '/auth'; return; }
                const d = document.getElementById('desc').value, s = document.getElementById('status'), f = document.getElementById('preview-frame'), c = document.getElementById('preview-container'), btn = document.getElementById('generateBtn'), sp = document.getElementById('spinner');
                if (!d) { s.textContent = 'Введите описание!'; return; }
                if (!currentUser.is_superuser && currentUser.generations_used >= FREE_LIMIT) { s.textContent = '🔒 Лимит бесплатных генераций исчерпан. Приобретите пакет в профиле!'; return; }
                isGenerating = true; btn.disabled = true; sp.style.display = 'block'; s.textContent = '⚡ Генерируем...';
                fetch('/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ description: d, email: currentUser.email, user_password: localStorage.getItem('siteforge_pass') || '' }) })
                .then(r => r.json()).then(data => {
                    if (data.error) { s.textContent = '❌ ' + data.error; }
                    else {
                        if (!currentUser.is_superuser) { currentUser.generations_used++; localStorage.setItem('siteforge_user', JSON.stringify(currentUser)); }
                        currentHtml = data.html; f.style.display = 'block'; c.style.display = 'block'; f.srcdoc = data.html;
                        s.textContent = '✅ Готово!'; updateTopBar();
                        setTimeout(() => { enableEditInFrame(); }, 500);
                    }
                }).catch(e => { s.textContent = '❌ Ошибка: ' + e.message; }).finally(() => { isGenerating = false; btn.disabled = false; sp.style.display = 'none'; });
            }
            
            function toggleEditMode() {
                editMode = !editMode;
                const btn = document.getElementById('edit-mode-btn');
                btn.textContent = editMode ? '✏️ Редактирование ВКЛ' : '✏️ Редактировать текст';
                btn.className = editMode ? 'edit-btn font-bold' : 'edit-btn';
                document.getElementById('edit-hint').style.display = editMode ? 'block' : 'none';
                enableEditInFrame();
            }
            
            function enableEditInFrame() {
                const frame = document.getElementById('preview-frame');
                if (!frame.srcdoc || frame.srcdoc === '') return;
                try {
                    const doc = frame.contentDocument || frame.contentWindow.document;
                    if (!doc) return;
                    const texts = doc.querySelectorAll('p, h1, h2, h3, h4, h5, h6, span, li, a, button, td, th, div, label');
                    texts.forEach(el => {
                        if (el.children.length === 0 && el.textContent.trim().length > 0) {
                            if (editMode) {
                                el.style.cursor = 'text';
                                el.style.outline = '1px dashed rgba(139,92,246,0.3)';
                                el.onclick = function(e) {
                                    e.preventDefault(); e.stopPropagation();
                                    const old = el.textContent;
                                    const input = doc.createElement('input');
                                    input.value = old; input.style.width = '100%'; input.style.padding = '4px';
                                    input.style.border = '2px solid #8b5cf6'; input.style.borderRadius = '4px';
                                    input.style.fontSize = window.getComputedStyle(el).fontSize;
                                    el.textContent = ''; el.appendChild(input); input.focus();
                                    input.onblur = function() {
                                        const newText = input.value;
                                        el.textContent = newText;
                                        currentHtml = currentHtml.replace(old, newText);
                                        el.style.outline = '1px dashed rgba(139,92,246,0.3)';
                                        el.style.cursor = 'text';
                                    };
                                    input.onkeydown = function(ev) { if (ev.key === 'Enter') input.blur(); };
                                };
                            } else {
                                el.style.cursor = 'default';
                                el.style.outline = 'none';
                                el.onclick = null;
                            }
                        }
                    });
                } catch(e) {}
            }
            
            function saveToGallery() {
    if (!currentHtml) { alert('Сначала создайте шаблон!'); return; }
    const title = document.getElementById('desc').value || 'Без названия';
    // Загружаем актуальную галерею перед сохранением
    gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
    gallery.unshift({ title, html: currentHtml, date: new Date().toLocaleString() });
    if (gallery.length > 50) gallery = gallery.slice(0, 50);
    localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
    renderGallery();
    document.getElementById('status').textContent = '💾 Сохранено в галерею!';
    setTimeout(() => { document.getElementById('status').textContent = '✅ Готово!'; }, 2000);
}
            
            function renderGallery() {
                const list = document.getElementById('gallery-list');
                const visible = gallery.slice(0, galleryVisible);
                list.innerHTML = visible.map((s, i) => `
                    <div class="site-card" onclick="loadFromGallery(${i})">
                        <div class="flex justify-between items-center">
                            <div style="max-width: 70%;">
                                <span class="text-sm font-medium" style="word-wrap: break-word; overflow-wrap: anywhere;">${s.title}</span>
                                <span class="text-xs text-gray-500 ml-2">${s.date}</span>
                            </div>
                            <button onclick="event.stopPropagation(); deleteFromGallery(${i})" class="text-red-400 text-xs hover:text-red-300">Удалить</button>
                        </div>
                    </div>
                `).join('');
                if (gallery.length > 4 && galleryVisible === 4) {
                    list.innerHTML += `<button onclick="showAll()" class="w-full text-center text-sm text-purple-400 hover:text-purple-300 py-2">Показать все (${gallery.length})</button>`;
                }
                if (!gallery.length) list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">Пока пусто. Создайте и сохраните первый шаблон!</p>';
            }
            
            function showAll() { galleryVisible = gallery.length; renderGallery(); }
            
            function loadFromGallery(i) {
                const s = gallery[i];
                currentHtml = s.html;
                document.getElementById('desc').value = s.title;
                const f = document.getElementById('preview-frame');
                f.srcdoc = s.html;
                f.style.display = 'block';
                document.getElementById('preview-container').style.display = 'block';
                document.getElementById('status').textContent = '📂 Загружено из галереи';
            }
            
            function deleteFromGallery(i) { if (confirm('Удалить?')) { gallery.splice(i, 1); localStorage.setItem('siteforge_gallery', JSON.stringify(gallery)); renderGallery(); } }
            function clearGallery() { if (confirm('Удалить ВСЁ?')) { gallery = []; localStorage.setItem('siteforge_gallery', JSON.stringify(gallery)); renderGallery(); } }
            function toggleGallery() { const s = document.getElementById('gallery-section'), b = document.getElementById('gallery-toggle'); if (s.style.display === 'block') { s.style.display = 'none'; b.textContent = '📂 Сохранённые шаблоны'; } else { s.style.display = 'block'; b.textContent = '📂 Скрыть шаблоны'; galleryVisible = 4; renderGallery(); } }
            function toggleCopyMenu() { document.getElementById('copyMenu').classList.toggle('active'); }
            function copyCode(mode) { if (!currentHtml) { alert('Сначала создайте шаблон!'); return; } let t = ''; if (mode === 'full') t = currentHtml; else if (mode === 'body') { const m = currentHtml.match(/<body[^>]*>([\\s\\S]*)<\\/body>/i); t = m ? m[1] : currentHtml; } else if (mode === 'css') { const m = currentHtml.match(/<style[^>]*>([\\s\\S]*)<\\/style>/i); t = m ? m[1] : '/* нет */'; } navigator.clipboard.writeText(t.trim()).then(() => { alert('Скопировано!'); toggleCopyMenu(); }); }
            function downloadHTML() { if (!currentHtml) { alert('Сначала создайте шаблон!'); return; } const b = new Blob([currentHtml], {type: 'text/html'}), u = URL.createObjectURL(b), a = document.createElement('a'); a.href = u; a.download = 'шаблон.html'; a.click(); URL.revokeObjectURL(u); }
            function closePreview() { document.getElementById('preview-frame').style.display = 'none'; document.getElementById('preview-container').style.display = 'none'; currentHtml = ''; editMode = false; document.getElementById('edit-mode-btn').textContent = '✏️ Редактировать текст'; document.getElementById('edit-hint').style.display = 'none'; }
            function openModal(t) { document.getElementById(t + '-modal').classList.add('active'); }
            function closeModal(t) { document.getElementById(t + '-modal').classList.remove('active'); }
            window.onclick = function(e) { if (e.target.classList.contains('modal')) e.target.classList.remove('active'); if (!e.target.closest('.copy-menu')) document.getElementById('copyMenu').classList.remove('active'); }
            document.addEventListener('mousemove', function(e) { const hint = document.getElementById('edit-hint'); if (editMode) { hint.style.left = (e.clientX + 15) + 'px'; hint.style.top = (e.clientY - 30) + 'px'; } });
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
            .package-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:24px;text-align:center}
            .package-card.popular{border-color:#f59e0b;background:rgba(245,158,11,0.05)}
            .btn-buy{background:#8b5cf6;color:white;padding:10px 24px;border-radius:10px;font-size:14px;font-weight:bold;border:none;opacity:0.5}
            .avatar-large{width:64px;height:64px;border-radius:50%;background:#8b5cf6;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:bold;margin:0 auto}
            .input-field{width:100%;padding:10px;border-radius:10px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:white;font-size:14px;outline:none;margin-bottom:8px}
            .btn-sm{background:#8b5cf6;color:white;padding:8px 16px;border-radius:10px;font-size:13px;font-weight:bold;border:none;cursor:pointer}
        </style>
    </head>
    <body class="bg-gray-950 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6">
            <a href="/" class="text-gray-400 hover:text-white text-sm">← Назад</a>
            <div class="bg-gray-900 rounded-2xl p-8 border border-gray-800 mt-4 relative">
                <div id="plo"><p class="text-center text-gray-400">Войдите. <a href="/auth" class="text-purple-400">Войти</a></p></div>
                <div id="pli" style="display:none">
                    <div class="avatar-large mb-4" id="pa"></div>
                    <h2 class="text-xl font-bold text-center mb-1" id="pe"></h2>
                    <p class="text-center text-3xl font-bold mb-2" id="pb"></p>
                    <div class="w-16 mx-auto border-b-2 border-purple-500 mb-6"></div>
                    <p class="text-center text-gray-400 text-sm mb-6">Приобрести генерации</p>
                    <div class="grid grid-cols-2 gap-3">
                        <div class="package-card"><h3 class="text-lg font-bold">5 ген.</h3><p class="text-2xl font-bold my-2">75₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card"><h3 class="text-lg font-bold">10 ген.</h3><p class="text-2xl font-bold my-2">140₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card popular"><h3 class="text-lg font-bold">30 ген.</h3><p class="text-2xl font-bold my-2">400₽</p><button class="btn-buy" disabled>Скоро</button></div>
                        <div class="package-card"><h3 class="text-lg font-bold">50 ген.</h3><p class="text-2xl font-bold my-2">600₽</p><button class="btn-buy" disabled>Скоро</button></div>
                    </div>
                    <div class="mt-6 flex justify-between items-end">
                        <div>
                            <button onclick="toggleChangePassword()" id="pwd-toggle-btn" class="text-red-400 hover:text-red-300 text-sm">Сменить пароль</button>
                            <div id="change-pwd-form" style="display:none; margin-top: 10px;">
                                <input id="old-pwd" type="password" placeholder="Старый пароль" class="input-field">
                                <input id="new-pwd" type="password" placeholder="Новый пароль" class="input-field">
                                <input id="confirm-pwd" type="password" placeholder="Подтвердите новый пароль" class="input-field">
                                <button onclick="changePassword()" class="btn-sm">Сохранить</button>
                                <p id="pwd-status" class="text-xs text-gray-400 mt-2"></p>
                            </div>
                        </div>
                        <button onclick="logout()" class="text-red-400 hover:text-red-300 text-sm">Выйти из аккаунта</button>
                    </div>
                </div>
            </div>
        </div>
        <script>
            const u = JSON.parse(localStorage.getItem('siteforge_user') || 'null');
            if (u) {
                document.getElementById('plo').style.display = 'none';
                document.getElementById('pli').style.display = 'block';
                document.getElementById('pa').textContent = u.email.charAt(0).toUpperCase();
                document.getElementById('pe').textContent = u.email;
                document.getElementById('pb').textContent = (u.is_superuser ? '∞' : Math.max(0, 3 - u.generations_used)) + ' ген.';
            }
            function toggleChangePassword() {
                const form = document.getElementById('change-pwd-form');
                const btn = document.getElementById('pwd-toggle-btn');
                if (form.style.display === 'block') {
                    form.style.display = 'none';
                    btn.textContent = 'Сменить пароль';
                } else {
                    form.style.display = 'block';
                    btn.textContent = 'Сменить пароль ▲';
                }
            }
            async function changePassword() {
                const oldPwd = document.getElementById('old-pwd').value;
                const newPwd = document.getElementById('new-pwd').value;
                const confirmPwd = document.getElementById('confirm-pwd').value;
                const s = document.getElementById('pwd-status');
                if (!oldPwd || !newPwd || !confirmPwd) { s.textContent = 'Заполните все поля'; return; }
                if (newPwd !== confirmPwd) { s.textContent = '❌ Новые пароли не совпадают'; return; }
                if (newPwd.length < 4) { s.textContent = '❌ Пароль от 4 символов'; return; }
                try {
                    const r = await fetch('/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: u.email, old_password: oldPwd, new_password: newPwd }) });
                    const d = await r.json();
                    if (r.ok) { s.textContent = '✅ Пароль изменён!'; localStorage.setItem('siteforge_pass', newPwd); }
                    else { s.textContent = '❌ ' + d.detail; }
                } catch(e) { s.textContent = '❌ Ошибка'; }
            }
            function logout() { localStorage.removeItem('siteforge_user'); localStorage.removeItem('siteforge_pass'); window.location.href = '/'; }
        </script>
    </body>
    </html>
    """

@app.get("/auth", response_class=HTMLResponse)
def auth_page():
    return """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SiteForge — Вход</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>"><script src="https://cdn.tailwindcss.com"></script><style>.input-field{width:100%;padding:14px;border-radius:14px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:white;font-size:15px;outline:none;margin-bottom:16px}.input-field:focus{border-color:#8b5cf6}.btn-primary{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;padding:14px;border-radius:14px;font-weight:bold;border:none;width:100%;cursor:pointer}</style></head><body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen"><div class="max-w-md w-full px-4 mx-auto py-12"><a href="/" class="text-gray-400 hover:text-white text-sm">← Назад</a><div class="text-center mb-8 mt-4"><div class="text-5xl mb-2">🚀</div><h1 class="text-2xl font-bold">Вход / Регистрация</h1></div><div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10"><div id="afl"><h3 class="text-sm font-bold mb-4">Вход</h3><input id="le" type="email" placeholder="Email" class="input-field"><input id="lp" type="password" placeholder="Пароль" class="input-field"><button onclick="login()" class="btn-primary mb-3">Войти</button><p class="text-xs text-gray-400 text-center mt-2">Нет аккаунта? <a href="#" onclick="showReg()" class="text-white font-bold hover:underline">Зарегистрироваться</a></p></div><div id="afr" style="display:none"><h3 class="text-sm font-bold mb-4">Регистрация</h3><input id="re" type="email" placeholder="Email" class="input-field"><input id="rp" type="password" placeholder="Пароль" class="input-field"><input id="rp2" type="password" placeholder="Подтвердите пароль" class="input-field"><button onclick="register()" class="btn-primary mb-3">Зарегистрироваться</button><p class="text-xs text-gray-400 text-center mt-2">Уже есть аккаунт? <a href="#" onclick="showLog()" class="text-white font-bold hover:underline">Войти</a></p></div><p id="as" class="mt-3 text-xs text-center text-gray-400"></p></div></div><script>function showLog(){document.getElementById('afl').style.display='block';document.getElementById('afr').style.display='none';document.getElementById('as').textContent=''}function showReg(){document.getElementById('afl').style.display='none';document.getElementById('afr').style.display='block';document.getElementById('as').textContent=''}async function login(){const e=document.getElementById('le').value,p=document.getElementById('lp').value,s=document.getElementById('as');if(!e||!p){s.textContent='Заполните все поля';return}try{const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});if(!r.ok){const d=await r.json();s.textContent='❌ '+d.detail}else{const u=await r.json();localStorage.setItem('siteforge_user',JSON.stringify(u));localStorage.setItem('siteforge_pass',p);s.textContent='✅ Вход выполнен!';setTimeout(()=>{window.location.href='/'},1000)}}catch(e){s.textContent='❌ Ошибка: '+e.message}}async function register(){const e=document.getElementById('re').value,p=document.getElementById('rp').value,p2=document.getElementById('rp2').value,s=document.getElementById('as');if(!e||!p||!p2){s.textContent='Заполните все поля';return}if(p!==p2){s.textContent='❌ Пароли не совпадают';return}if(p.length<4){s.textContent='❌ Пароль от 4 символов';return}try{const r=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});const d=await r.json();if(!r.ok){s.textContent='❌ '+d.detail}else{s.textContent='✅ Регистрация успешна! Теперь войдите.';showLog();document.getElementById('le').value=e}}catch(e){s.textContent='❌ Ошибка: '+e.message}}</script></body></html>"""

@app.get("/thanks", response_class=HTMLResponse)
def thanks_page():
    return """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SiteForge — Спасибо!</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>"><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen flex items-center justify-center"><div class="text-center px-4"><div class="text-6xl mb-4">🎉</div><h1 class="text-3xl font-bold mb-2">Спасибо за покупку!</h1><p class="text-gray-400 mb-6">Генерации скоро будут начислены на Ваш баланс.</p><a href="/profile" class="bg-purple-600 hover:bg-purple-700 text-white px-6 py-3 rounded-xl font-bold transition">Вернуться в профиль</a></div></body></html>"""