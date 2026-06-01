import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("PROXYAPI_KEY"),
    base_url="https://api.proxyapi.ru/openai/v1"
)

app = FastAPI()

PASSWORD = "123098123098"
last_site = {"html": ""}

class SiteRequest(BaseModel):
    description: str
    password: str

class EditRequest(BaseModel):
    html: str
    old_text: str
    new_text: str

@app.post("/edit")
def edit_html(req: EditRequest):
    new_html = req.html.replace(req.old_text, req.new_text)
    return {"html": new_html}

@app.post("/generate")
def generate_site(req: SiteRequest):
    global last_site
    if req.password != PASSWORD:
        return {"error": "Неверный пароль"}
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты генератор HTML-шаблонов. Пользователь описывает, какой шаблон нужен. "
                    "Создай КРАСИВЫЙ современный адаптивный одностраничный HTML-шаблон с Tailwind CSS (подключи через CDN). "
                    "Используй ТЁМНУЮ тему по умолчанию (тёмный фон, светлый текст), если пользователь явно не просит светлую. "
                    "Шаблон должен быть полностью адаптивным для мобильных устройств (используй responsive классы Tailwind: sm:, md:, lg:). "
                    "Не допускай горизонтальной прокрутки на телефонах. Используй max-width: 100vw и overflow-x: hidden на body. "
                    "Все ссылки и кнопки должны быть НЕАКТИВНЫМИ заглушками (href='#' или onclick='return false'). Не используй реальные ссылки. "
                    "Используй красивые градиенты, тени, анимации при наведении. "
                    "Отвечай ТОЛЬКО HTML-кодом в ```html ... ```. Без пояснений."
                )
            },
            {
                "role": "user",
                "content": f"Создай шаблон по описанию: {req.description}"
            }
        ],
        temperature=0.8,
        max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()
    if "```html" in raw:
        html = raw.split("```html")[1].split("```")[0].strip()
    elif "```" in raw:
        html = raw.split("```")[1].split("```")[0].strip()
    else:
        html = raw
    # Делаем все ссылки неактивными
    import re
    html = re.sub(r'href="[^"]*"', 'href="#"', html)
    html = re.sub(r"href='[^']*'", "href='#'", html)
    html = re.sub(r'action="[^"]*"', 'action="#"', html)

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
            #preview-frame { width: 100%; height: 70vh; border: none; border-radius: 12px; display: none; background: #1a1a2e; }
            #preview-container { display: none; margin-top: 20px; animation: fadeIn 0.3s ease; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            .spinner { animation: spin 1s linear infinite; width: 30px; height: 30px; border: 3px solid rgba(255,255,255,0.2); border-top-color: #8b5cf6; border-radius: 50%; display: none; margin: 10px auto; }
            .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 10px 20px; border-radius: 12px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; }
            .btn-primary:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(99,102,241,0.4); }
            .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
            .site-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s; backdrop-filter: blur(10px); }
            .site-card:hover { background: rgba(255,255,255,0.1); transform: translateX(4px); }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; }
            .modal.active { display: flex; }
            .modal-content { background: #0f0d2e; border-radius: 16px; padding: 24px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); color: #d1d5db; }
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-6 relative">
            <!-- Top right buttons -->
            <div class="absolute top-4 right-4 flex gap-2">
                <button onclick="openModal('help')" class="text-gray-500 hover:text-gray-300 text-xs transition">Помощь</button>
                <button onclick="openModal('about')" class="text-gray-500 hover:text-gray-300 text-xs transition">О нас</button>
            </div>
            
            <!-- Header -->
            <div class="text-center mb-6">
                <div class="text-5xl mb-2">🚀</div>
                <h1 class="text-3xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1>
                <p class="text-gray-400 mt-1 text-sm">Генератор HTML-шаблонов с помощью ИИ</p>
            </div>
            
            <!-- Form Card -->
            <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-5 border border-white/10 shadow-2xl">
                <input id="password" type="password" placeholder="🔑 Пароль"
                       class="w-full p-3 rounded-xl bg-white/5 border border-white/10 text-white mb-3
                              focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-500">
                <input id="desc" type="text" placeholder="💡 Опиши шаблон, например: лендинг для кофейни"
                       class="w-full p-3 rounded-xl bg-white/5 border border-white/10 text-white mb-4
                              focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-500"
                       maxlength="500">
                <button id="generateBtn" onclick="generate()" class="w-full p-4 btn-primary text-lg">
                    ✨ Создать шаблон
                </button>
                <div class="spinner" id="spinner"></div>
                <p id="status" class="mt-3 text-gray-400 text-xs text-center"></p>
            </div>
            
            <!-- Preview -->
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
            
            <!-- Gallery -->
            <div id="gallery-section" style="display:none; margin-top: 30px;">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-bold">📂 Мои шаблоны</h2>
                    <button onclick="clearGallery()" class="text-xs text-gray-500 hover:text-red-400">Очистить</button>
                </div>
                <div id="gallery-list"></div>
            </div>
            
            <!-- Gallery Toggle -->
            <div class="text-center mt-4">
                <button onclick="toggleGallery()" class="text-sm text-gray-400 hover:text-white transition" id="gallery-toggle">
                    📂 Сохранённые шаблоны
                </button>
            </div>
            
            <!-- Google Play -->
            <div class="text-center mt-6 pb-6">
                <p class="text-xs text-gray-500">📱 Скоро в Google Play — SiteForge</p>
            </div>
        </div>

        <!-- Help Modal -->
        <div id="help-modal" class="modal">
            <div class="modal-content">
                <div class="flex justify-between items-center mb-3">
                    <h2 class="text-lg font-bold text-white">Как пользоваться</h2>
                    <button onclick="closeModal('help')" class="text-gray-500 hover:text-red-400 text-xl leading-none transition">✕</button>
                </div>
                <div class="text-sm space-y-2">
                    <p><strong>1.</strong> Введи пароль (получи у администратора).</p>
                    <p><strong>2.</strong> Опиши шаблон: для кого, какой стиль, какие секции нужны.</p>
                    <p><strong>3.</strong> Нажми «Создать шаблон» и жди пару секунд.</p>
                    <p><strong>4.</strong> Сохрани, скачай или скопируй HTML-код.</p>
                    <p><strong>5.</strong> Открой в любом редакторе и доработай под себя.</p>
                    <p class="text-gray-400 mt-3"><strong>Примеры запросов:</strong></p>
                    <p class="text-gray-500">— лендинг для кофейни с меню и отзывами</p>
                    <p class="text-gray-500">— сайт-визитка фотографа с портфолио</p>
                    <p class="text-gray-500">— одностраничный магазин кроссовок</p>
                </div>
            </div>
        </div>

        <!-- About Modal -->
        <div id="about-modal" class="modal">
            <div class="modal-content">
                <div class="flex justify-between items-center mb-3">
                    <h2 class="text-lg font-bold text-white">О нас</h2>
                    <button onclick="closeModal('about')" class="text-gray-500 hover:text-red-400 text-xl leading-none transition">✕</button>
                </div>
                <div class="text-sm space-y-2">
                    <p><strong>SiteForge</strong> — это генератор HTML-шаблонов с помощью искусственного интеллекта.</p>
                    <p>Мы создаём красивые адаптивные заготовки для сайтов за секунды. Вам остаётся только заменить текст и изображения.</p>
                    <p>Идеально для верстальщиков, фрилансеров и студентов.</p>
                    <p class="text-gray-400 mt-3">Версия: 1.0</p>
                    <p class="text-gray-400">Сделано с ❤️</p>
                </div>
            </div>
        </div>
        
        <script>
            let currentHtml = '';
            let isGenerating = false;
            let gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
            
            function generate() {
                if (isGenerating) return;
                const password = document.getElementById('password').value;
                const desc = document.getElementById('desc').value;
                const status = document.getElementById('status');
                const frame = document.getElementById('preview-frame');
                const container = document.getElementById('preview-container');
                const btn = document.getElementById('generateBtn');
                const spinner = document.getElementById('spinner');
                
                if (!desc) { status.textContent = 'Введи описание!'; return; }
                if (!password) { status.textContent = 'Введи пароль!'; return; }
                
                isGenerating = true;
                btn.disabled = true;
                spinner.style.display = 'block';
                status.textContent = '⚡ Генерирую...';
                
                fetch('/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ description: desc, password: password })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.error) {
                        status.textContent = '❌ ' + data.error;
                    } else {
                        currentHtml = data.html;
                        frame.style.display = 'block';
                        container.style.display = 'block';
                        frame.srcdoc = data.html;
                        status.textContent = '✅ Готово!';
                    }
                })
                .catch(e => { status.textContent = '❌ Ошибка: ' + e.message; })
                .finally(() => {
                    isGenerating = false;
                    btn.disabled = false;
                    spinner.style.display = 'none';
                    setTimeout(() => { status.textContent = ''; }, 3000);
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
                list.innerHTML = gallery.map((site, i) => `
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
                if (gallery.length === 0) list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">Пока пусто</p>';
            }
            
            function loadFromGallery(index) {
                const site = gallery[index];
                currentHtml = site.html;
                document.getElementById('desc').value = site.title;
                document.getElementById('preview-frame').srcdoc = site.html;
                document.getElementById('preview-frame').style.display = 'block';
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
                const section = document.getElementById('gallery-section');
                const btn = document.getElementById('gallery-toggle');
                if (section.style.display === 'block') {
                    section.style.display = 'none';
                    btn.textContent = '📂 Сохранённые шаблоны';
                } else {
                    section.style.display = 'block';
                    btn.textContent = '📂 Скрыть шаблоны';
                    renderGallery();
                }
            }
            
            function copyCode() {
                if (!currentHtml) { alert('Сначала создай шаблон!'); return; }
                navigator.clipboard.writeText(currentHtml).then(() => alert('Скопировано!'));
            }
            
            function downloadHTML() {
                if (!currentHtml) { alert('Сначала создай шаблон!'); return; }
                const blob = new Blob([currentHtml], {type: 'text/html'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'шаблон.html';
                a.click();
                URL.revokeObjectURL(url);
            }
            
            function closePreview() {
                document.getElementById('preview-frame').style.display = 'none';
                document.getElementById('preview-container').style.display = 'none';
                currentHtml = '';
            }
            
            function openModal(type) {
                document.getElementById(type + '-modal').classList.add('active');
            }
            
            function closeModal(type) {
                document.getElementById(type + '-modal').classList.remove('active');
            }
            
            window.onclick = function(e) {
                if (e.target.classList.contains('modal')) {
                    e.target.classList.remove('active');
                }
            }
            
            renderGallery();
        </script>
    </body>
    </html>
    """