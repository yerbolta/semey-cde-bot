"""
Telegram-бот для 018-SEMEY-MY — версия для БЕСПЛАТНОГО хостинга на Render.com

Отличие от версии с polling: этот вариант работает через webhook (Telegram
сам присылает HTTP-запрос при новом сообщении), что подходит для
бесплатного тарифа Render, который не держит процесс запущенным вечно,
а "просыпается" по входящему запросу.

НАСТРОЙКА — см. README_бесплатный_хостинг_Render.md рядом с этим файлом.
"""

import os
import logging
import requests
from flask import Flask, request, jsonify
from anthropic import Anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-5"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

client = Anthropic(api_key=ANTHROPIC_API_KEY)
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Системная инструкция — правила проекта 018-SEMEY-MY
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
Ты — помощник по проектной документации компании Metcon, для проекта
018-SEMEY-MY (Gold Ore Processing Plant, месторождение вблизи Семей).

КОНТЕКСТ ПРОЕКТА
Четыре стороны: Metcon (казахская проектная компания, ГАП — Ербол),
YPT (турецкий проектировщик), China (поставщик оборудования),
Miryildiz (заказчик). Плюс экспертиза, которая согласует проект.

ТРИ РОЛИ METCON — используй именно эту классификацию при ответах:
1. "Проектирует сам" — большинство зданий, все разделы Metcon делает
   с нуля (ГП, АР, КР, ОВ, ВК, ЭОМ, СС, ПОС, ПБ, ООС, СМЕТА).
2. "Переоформляет" — разделы КЖ/КМ трёх конкретных зданий полностью
   делает YPT, Metcon переоформляет их под свой штамп.
3. "На основе входных данных" — раздел ТХ (технология): China и YPT
   дают технологические требования и спецификации оборудования,
   Metcon сам проектирует раздел ТХ на основе этих данных.

СИСТЕМА ПАПОК (принцип CDE / ISO 19650)
0_WIP        — в работе, черновики
1_SHARED     — согласовано внутри, можно опираться другим разделам
2_PUBLISHED  — официально выпущено вовне (заказчику, экспертизе)
3_ARCHIVE    — устаревшие ревизии, ничего не удаляется вручную
0_ADMIN      — договор, ТЗ, реестры

СТРУКТУРА ПО ЗДАНИЯМ — ПЕРВЫЙ УРОВЕНЬ ПАПКИ, ВТОРОЙ — РАЗДЕЛ:
0_WIP/Metcon/[здание]/[раздел]/
Коды зданий: 0000 (Site-Wide, общеплощадочные документы), 1000, 2000,
3000 (эти три — YPT делает КЖ/КМ, Metcon переоформляет), 4000, 5000,
6000, 7000, 8000 (Metcon проектирует полностью сам). Актуальные
названия зданий — лист "Здания" в Реестры_SEMEY.xlsx.

ВНУТРИ КАЖДОГО ЗДАНИЯ, В КАЖДОМ РАЗДЕЛЕ — ОДНО ПРАВИЛО БЕЗ ИСКЛЮЧЕНИЙ:
0_WIP/Metcon/[здание]/[раздел]/
├── _sketches/       — свои эскизы и черновики, любые имена, версий сколько угодно
├── _source_YPT/     — чужие файлы от YPT, кладём как есть, не трогаем
├── _source_China/   — чужие файлы от China, кладём как есть, не трогаем
└── (сам раздел)     — документ, который выпускает Metcon

ОДНО ПРАВИЛО ДЛЯ ЛЮБОГО РАЗДЕЛА, БЕЗ ИСКЛЮЧЕНИЙ:
0_WIP/Metcon/[раздел]/
├── _sketches/       — свои эскизы и черновики, любые имена, версий сколько угодно
├── _source_YPT/     — чужие файлы от YPT, кладём как есть, не трогаем
├── _source_China/   — чужие файлы от China, кладём как есть, не трогаем
└── (сам раздел)     — документ, который выпускает Metcon

ИМЕНОВАНИЕ ФАЙЛОВ
SEM[ФАЗА]-[ORG]-[AREA]-[DISC]-[NUMBER]_[REV]
ФАЗА: SEM1 / SEM2 / SEM3 / SEM4 — фаза строительства, к которой
относится здание/чертёж (с 2026-10-27; LEVEL и TYPE убраны).
ORG: MTC / YPT / CHN
AREA — код здания (0000, 1000 ... 12001), тот же, что и папка здания.
DISC — раздел, как называется папка: AR, КЖ, КМ, OV, VK, EOM, TX, SS,
GP, POS, PB, OOS, SMETA (КЖ/КМ кириллицей, остальные латиницей).
NUMBER — порядковый номер, 4 цифры.
Пример: SEM1-MTC-1000-AR-0001_P01.dwg
        SEM1-MTC-11000-КЖ-0001_C01.pdf
REV: P01, P02... — в разработке (WIP)
     C01, C02... — официально выпущено (Shared/Published)

Если в одном DWG несколько листов (Layout) — в реестре заводится
отдельная строка на каждый лист, с суффиксом кода -L1, -L2 и т.д.,
но с одним и тем же именем физического файла.

№ ЛИСТА В ШТАМПЕ — короткий номер по казахстанской норме (1, 2, 3...),
не совпадает с длинным кодом файла. Хранится отдельной колонкой
в реестре, соответствие видно там же.

ДВА РЕЕСТРА — ведутся в Google Sheets (с 2026-07-15, не в Excel):
https://docs.google.com/spreadsheets/d/1Rt7h5h_DvBQY_QGZnlYIoS6VubMfoecY1hdATD6JBP0/edit
- Document Register — одна строка на лист документа: код листа, имя
  DWG-файла, № листа в штампе, раздел, здание, роль Metcon, источник
  исходных данных, ревизия, статус, даты, кому передано.
- Transmittal Log — одна строка на каждую передачу файлов между
  сторонами: дата, от кого, кому, что, цель, статус ответа.

КАК ОТВЕЧАТЬ СОТРУДНИКАМ
- Если вопрос "куда положить файл" — определи раздел, роль Metcon
  (сам/переоформляет/на основе входных данных) и укажи точный путь.
- Если вопрос про имя файла — разложи по системе кодирования,
  укажи правильную ревизию (P vs C).
- Если вопрос про реестр или "где реестр" — дай ссылку на Google Sheets
  выше и укажи, в какой из двух листов и какую строку/колонку заполнить.
- Если ситуация не описана в базе — прямо скажи, что это не
  предусмотрено текущими правилами, и предложи уточнить у Ербола
  (ГАП), а не придумывай новое правило от себя.
- Отвечай кратко и конкретно, сразу путём/примером, без пересказа
  теории CDE каждый раз заново.
- Пиши по-русски, если сотрудник не написал на другом языке.
"""

# Память по чатам — в оперативной памяти процесса. На бесплатном тарифе
# Render процесс перезапускается при "засыпании", так что память не
# долгосрочная — этого достаточно для справочных вопросов.
chat_histories: dict[int, list[dict]] = {}
MAX_HISTORY_MESSAGES = 10

REGISTRY_URL = "https://docs.google.com/spreadsheets/d/1Rt7h5h_DvBQY_QGZnlYIoS6VubMfoecY1hdATD6JBP0/edit"
REGISTRY_KEYWORDS = ("реестр", "registry", "таблиц", "sheet", "гугл шит", "google sheet")


def is_registry_question(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in REGISTRY_KEYWORDS)


def send_telegram_message(chat_id: int, text: str) -> None:
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})


def ask_claude(chat_id: int, user_text: str) -> str:
    history = chat_histories.get(chat_id, [])
    history.append({"role": "user", "content": user_text})

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    answer = "".join(block.text for block in response.content if block.type == "text")

    history.append({"role": "assistant", "content": answer})
    chat_histories[chat_id] = history[-MAX_HISTORY_MESSAGES:]
    return answer


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True)
    message = update.get("message")
    if not message or "text" not in message:
        return jsonify(ok=True)

    chat_id = message["chat"]["id"]
    text = message["text"]

    if text == "/start":
        send_telegram_message(
            chat_id,
            "Привет! Я помощник по проектной документации 018-SEMEY-MY.\n"
            "Спрашивайте: куда положить файл, как назвать, что писать в реестр — отвечу по нашим правилам.",
        )
        return jsonify(ok=True)

    if text == "/reset":
        chat_histories.pop(chat_id, None)
        send_telegram_message(chat_id, "Контекст диалога очищен.")
        return jsonify(ok=True)

    if is_registry_question(text):
        send_telegram_message(
            chat_id,
            "Реестры (Document Register, Transmittal Log, Здания, Чек-лист разделов) — здесь:\n"
            f"{REGISTRY_URL}",
        )
        return jsonify(ok=True)

    try:
        answer = ask_claude(chat_id, text)
    except Exception as e:
        logger.exception("Anthropic API error")
        answer = f"Ошибка при обращении к Claude API: {e}"

    send_telegram_message(chat_id, answer)
    return jsonify(ok=True)


@app.route("/", methods=["GET"])
def health():
    return "Semey CDE bot is running."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
