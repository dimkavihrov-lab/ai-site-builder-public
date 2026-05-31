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
                    "Ты генератор сайтов. Пользователь описывает, какой сайт нужен. "
                    "Создай КРАСИВЫЙ современный адаптивный одностраничный сайт на HTML с Tailwind CSS (подключи через CDN). "
                    "Сайт должен быть полностью адаптивным для мобильных устройств (используй responsive классы Tailwind: sm:, md:, lg:). "
                    "Не допускай горизонтальной прокрутки на телефонах. Используй max-width: 100vw и overflow-x: hidden на body. "
                    "Используй градиенты, красивые тени, анимации при наведении. "
                    "Отвечай ТОЛЬКО HTML-кодом в ```html ... ```. Без пояснений."
                )
            },
            {
                "role": "user",
                "content": f"Создай сайт по описанию: {req.description}"
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
        <title>SiteForge — Генератор сайтов</title>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚀</text></svg>">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            #preview-frame { width: 100%; height: 70vh; border: none; border-radius: 12px; display: none; background: white; }
            #preview-container { display: none; margin-top: 20px; animation: fadeIn 0.3s ease; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 10px 20px; border-radius: 12px; font-weight: bold; cursor: pointer; border: none; transition: all 0.2s; }
            .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(99,102,241,0.4); }
            .btn-success { background: #10b981; color: white; padding: 8px 16px; border-radius: 10px; font-size: 13px; cursor: pointer; border: none; transition: all 0.2s; }
            .btn-success:hover { background: #059669; }
            .btn-download { background: #f59e0b; color: white; padding: 8px 16px; border-radius: 10px; font-size: 13px; cursor: pointer; border: none; transition: all 0.2s; }
            .btn-download:hover { background: #d97706; }
            .site-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s; backdrop-filter: blur(10px); }
            .site-card:hover { background: rgba(255,255,255,0.1); transform: translateX(4px); }
            .gallery-section { display: none; margin-top: 30px; animation: fadeIn 0.3s ease; }
        </style>
    </head>
    <body class="bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 text-white min-h-screen">
        <div class="max-w-2xl w-full px-4 mx-auto py-8">
            <!-- Header -->
            <div class="text-center mb-8">
                <div class="text-6xl mb-3">🚀</div>
                <h1 class="text-4xl font-extrabold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">SiteForge</h1>
                <p class="text-gray-400 mt-2 text-sm">Создай красивый сайт за секунды с помощью ИИ</p>
            </div>
            
            <!-- Form Card -->
            <div class="bg-white/5 backdrop-blur-lg rounded-2xl p-6 border border-white/10 shadow-2xl">
                <input id="password" type="password" placeholder="🔑 Пароль"
                       class="w-full p-3.5 rounded-xl bg-white/5 border border-white/10 text-white mb-3
                              focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-500">
                <input id="desc" type="text" placeholder="💡 Опиши сайт, например: магазин кроссовок с каталогом"
                       class="w-full p-3.5 rounded-xl bg-white/5 border border-white/10 text-white mb-4
                              focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-500">
                <button onclick="generate()" class="w-full p-4 btn-primary text-lg">
                    ✨ Создать сайт
                </button>
                <p id="status" class="mt-3 text-gray-400 text-xs text-center"></p>
            </div>
            
            <!-- Preview -->
            <div id="preview-container">
                <div class="flex justify-between items-center mb-3 flex-wrap gap-2">
                    <span class="text-sm text-gray-300">👁 Предпросмотр</span>
                    <div class="flex gap-2">
                        <button onclick="saveToGallery()" class="btn-success">💾 Сохранить</button>
                        <button onclick="downloadHTML()" class="btn-download">📥 Скачать</button>
                        <button onclick="copyCode()" class="btn-success">📋 Копировать</button>
                        <button onclick="closePreview()" class="text-red-400 text-sm hover:text-red-300">✕</button>
                    </div>
                </div>
                <iframe id="preview-frame"></iframe>
            </div>
            
            <!-- Gallery -->
            <div id="gallery-section" class="gallery-section">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-xl font-bold">📂 Мои сайты</h2>
                    <button onclick="clearGallery()" class="text-xs text-gray-500 hover:text-red-400">Очистить всё</button>
                </div>
                <div id="gallery-list"></div>
            </div>
            
            <!-- Toggle Gallery Button -->
            <div class="text-center mt-6">
                <button onclick="toggleGallery()" class="text-sm text-gray-400 hover:text-white transition" id="gallery-toggle">
                    📂 Показать сохранённые сайты
                </button>
            </div>
        </div>
        
        <script>
            let currentHtml = '';
            let gallery = JSON.parse(localStorage.getItem('siteforge_gallery') || '[]');
            
            function generate() {
                const password = document.getElementById('password').value;
                const desc = document.getElementById('desc').value;
                const status = document.getElementById('status');
                const frame = document.getElementById('preview-frame');
                const container = document.getElementById('preview-container');
                
                if (!desc) { status.textContent = 'Введи описание!'; return; }
                if (!password) { status.textContent = 'Введи пароль!'; return; }
                
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
                .catch(e => { status.textContent = '❌ Ошибка: ' + e.message; });
            }
            
            function saveToGallery() {
                if (!currentHtml) { alert('Сначала создай сайт!'); return; }
                const title = document.getElementById('desc').value || 'Без названия';
                gallery.unshift({ title: title, html: currentHtml, date: new Date().toLocaleString() });
                if (gallery.length > 50) gallery = gallery.slice(0, 50);
                localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
                renderGallery();
                const status = document.getElementById('status');
                status.textContent = '💾 Сохранено!';
                setTimeout(() => { status.textContent = '✅ Готово!'; }, 1500);
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
                if (gallery.length === 0) list.innerHTML = '<p class="text-gray-500 text-sm text-center py-4">Пока пусто. Создайте сайт и нажмите «Сохранить».</p>';
            }
            
            function loadFromGallery(index) {
                const site = gallery[index];
                currentHtml = site.html;
                document.getElementById('desc').value = site.title;
                document.getElementById('preview-frame').srcdoc = site.html;
                document.getElementById('preview-frame').style.display = 'block';
                document.getElementById('preview-container').style.display = 'block';
                document.getElementById('status').textContent = '📂 Загружено из галереи';
            }
            
            function deleteFromGallery(index) {
                if (confirm('Удалить этот сайт из галереи?')) {
                    gallery.splice(index, 1);
                    localStorage.setItem('siteforge_gallery', JSON.stringify(gallery));
                    renderGallery();
                }
            }
            
            function clearGallery() {
                if (confirm('Удалить ВСЕ сохранённые сайты?')) {
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
                    btn.textContent = '📂 Показать сохранённые сайты';
                } else {
                    section.style.display = 'block';
                    btn.textContent = '📂 Скрыть сохранённые сайты';
                    renderGallery();
                }
            }
            
            function copyCode() {
                if (!currentHtml) { alert('Сначала создай сайт!'); return; }
                navigator.clipboard.writeText(currentHtml).then(() => {
                    const status = document.getElementById('status');
                    status.textContent = '📋 Скопировано в буфер обмена!';
                    setTimeout(() => { status.textContent = '✅ Готово!'; }, 1500);
                });
            }
            
            function downloadHTML() {
                if (!currentHtml) { alert('Сначала создай сайт!'); return; }
                const blob = new Blob([currentHtml], {type: 'text/html'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'сайт.html';
                a.click();
                URL.revokeObjectURL(url);
            }
            
            function closePreview() {
                document.getElementById('preview-frame').style.display = 'none';
                document.getElementById('preview-container').style.display = 'none';
                document.getElementById('status').textContent = '';
                currentHtml = '';
            }
            
            renderGallery();
        </script>
    </body>
    </html>
    """