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

PASSWORD = "123098123098"  # Поменяй на свой пароль
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
                    "Создай КРАСИВЫЙ современный одностраничный сайт на HTML с Tailwind CSS (подключи через CDN). "
                    "Используй градиенты, иконки, красивые тени, анимации при наведении. "
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Генератор сайтов</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gradient-to-br from-gray-900 via-purple-900 to-gray-900 text-white min-h-screen flex items-center justify-center">
        <div class="text-center max-w-lg w-full px-4">
            <div class="text-6xl mb-4">🚀</div>
            <h1 class="text-4xl font-bold mb-2 bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">Генератор сайтов</h1>
            <p class="text-gray-300 mb-6">Опиши сайт — и он появится за секунды</p>
            <input id="password" type="password" placeholder="Пароль"
                   class="w-full p-4 rounded-xl bg-gray-800 border border-gray-700 text-white mb-3
                          focus:outline-none focus:ring-2 focus:ring-purple-500">
            <input id="desc" type="text" placeholder="Например: сайт кофейни с меню и отзывами"
                   class="w-full p-4 rounded-xl bg-gray-800 border border-gray-700 text-white mb-4
                          focus:outline-none focus:ring-2 focus:ring-purple-500">
            <button onclick="generate()"
                    class="w-full p-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 rounded-xl font-bold text-lg transition shadow-lg">
                Создать сайт
            </button>
            <p id="status" class="mt-4 text-gray-400"></p>
        </div>
        <script>
            async function generate() {
                const password = document.getElementById('password').value;
                const desc = document.getElementById('desc').value;
                const status = document.getElementById('status');
                if (!desc) { status.textContent = 'Введи описание!'; return; }
                if (!password) { status.textContent = 'Введи пароль!'; return; }
                status.textContent = 'Генерирую...';
                try {
                    const res = await fetch('/generate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ description: desc, password: password })
                    });
                    const data = await res.json();
                    if (data.error) {
                        status.textContent = 'Ошибка: ' + data.error;
                    } else {
                        window.open('/view', '_blank');
                        status.textContent = 'Готово! Сайт открыт в новой вкладке.';
                    }
                } catch (e) {
                    status.textContent = 'Ошибка: ' + e.message;
                }
            }
        </script>
    </body>
    </html>
    """