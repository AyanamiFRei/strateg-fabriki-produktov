"""Build a narrated, screen-free walkthrough from demo artifacts and real CLI screenshots.

Windows-only optional builder. Requires Pillow, opencv-python, pywin32 and ffmpeg.
The video is composed from repository artifacts; it does not record the desktop.
"""
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np
import win32com.client
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SIZE = (1920, 1080)
FPS = 24
SCENES = [
    {
        "title": "Стратег Фабрики продуктов",
        "subtitle": "От неоднозначного вопроса до стратегии и пересмотра решения",
        "bullets": ["Инструкции и знания отделены от материалов проекта", "Модель формулирует выводы, CLI проверяет воспроизводимые вещи", "Человек выбирает направление и принимает итог"],
        "image": "docs/screenshots/architecture.png",
        "voice": "Это Стратег Фабрики продуктов: папка агента для продуктовых команд. Модель ведёт исследование по стадиям, а локальный инструмент проверяет реестр фактов, расчёты, сроки и решения. Покажу пример на учебном брифе: от постановки задачи до пересмотра уже принятого решения.",
    },
    {
        "title": "Запрос и границы задачи",
        "subtitle": "Демо-проект demo-family · учебный бриф",
        "bullets": ["Вопрос: кому помочь со связью в первую очередь?", "Цель: обоснованное решение о пилоте к концу Q1", "Ограничения и отсутствующие данные фиксируются до рекомендации"],
        "image": "docs/screenshots/progress.png",
        "voice": "На входе учебный PDF-бриф о семейных группах вымышленного оператора и сохранённые материалы открытых страниц. Агент фиксирует, кто принимает решения, к какому сроку, какие ограничения заданы и каких данных нет. В этом примере нет клиентской базы и реальных интервью; бизнес-показатели из брифа являются учебными.",
    },
    {
        "title": "Сбор и проверяемые основания",
        "subtitle": "Факт принимается только с источником и найденной цитатой",
        "bullets": ["Снимки открытых источников сохраняются в проекте", "Гипотезы и допущения помечены отдельно от фактов", "Команда why показывает цепочку до основания"],
        "image": "docs/screenshots/why.png",
        "voice": "Источники хранятся вместе с проектом, а существенные утверждения имеют тип и ссылку: факт, допущение, гипотеза, прогноз или расчёт. Команда why показывает цепочку от числа к расчёту и основаниям. Сохранённый текст страницы считается данными, а не инструкцией для агента. Если цитата не найдена в зарегистрированном снимке, строка не становится фактом.",
    },
    {
        "title": "Работа продолжается после перерыва",
        "subtitle": "Команда resume восстанавливает состояние задачи",
        "bullets": ["Текущая стадия и пройденные ворота", "Ожидаемое действие человека", "Следующий шаг и стоимость"],
        "image": "docs/screenshots/resume.png",
        "voice": "Если работа прервалась, новый чат начинает с команды resume. Она показывает стадию, пройденные точки выбора, текущий статус, следующий шаг и известную стоимость. Агент продолжает с сохранённого состояния, а не пересказывает предыдущий документ как доказательство. Для важных развилок он ждёт решения руководителя.",
    },
    {
        "title": "Диагноз и варианты",
        "subtitle": "Сигнал не подменяет причину; сравниваются разные ходы",
        "bullets": ["Известно: у близкого может прерваться интернет", "Неизвестно: как часто и почему это происходит", "Пять вариантов включают «оставить как есть» и «закрыть направление»"],
        "image": "projects/demo-family/deliverables/critique.md",
        "voice": "Диагноз отделяет наблюдаемый сигнал от объяснения. Бриф задаёт проблему и цели, но частоты причин и подходящих случаев неизвестны, поэтому это не выдаётся за установленный спрос. Варианты сравниваются для одной ситуации: от сохранения текущего подхода до закрытия направления, включая пилот и альтернативные продуктовые действия. У каждого варианта записаны сильное возражение и данные, которые могли бы изменить выбор. Критик отдельно проверяет расчёты и логику вариантов.",
    },
    {
        "title": "Продуктовая стратегия",
        "subtitle": "Один узкий сегмент и одна операция до конца",
        "bullets": ["Аудитория: организаторы семейных групп", "Идея: уведомить при низком остатке у участника", "Кнопка ведёт к существующей операции добавления интернета"],
        "image": "projects/demo-family/deliverables/product_strategy.md",
        "voice": "Рекомендован ограниченный пилот: уведомление организатору, когда у участника заканчивается интернет, при наличии свободного объёма в общем пакете. Действие ведёт к уже существующей операции «Добавить интернет». Оно зависит от согласия участника. В документах отдельно указано, что эта инициатива не закрывает весь заданный финансовый разрыв и сама по себе не обосновывает масштабирование.",
    },
    {
        "title": "Коммуникационная стратегия",
        "subtitle": "Обещание связано с функцией и условием",
        "bullets": ["Сообщение объясняет, что интернет заканчивается", "Показывается доступный общий объём", "Обещание подтверждается существующей функцией и согласием"],
        "image": "projects/demo-family/deliverables/comms_strategy.md",
        "voice": "Коммуникация строится вокруг конкретной ситуации: у близкого заканчивается интернет, а организатор может помочь. Сообщение показывает остаток и ведёт к существующей операции. Обещание ограничено тем, что продукт действительно делает, а отправка зависит от разрешения участника. Канал и формулировка не обещают автоматического пополнения или гарантированного улучшения удержания.",
    },
    {
        "title": "План проверки",
        "subtitle": "Операционный сигнал и полезный результат наблюдаются отдельно",
        "bullets": ["Сравнение пилота с контрольной группой", "Заданы срок, метрика и условия остановки", "Результат пилота не равен доказанному долгосрочному эффекту"],
        "image": "projects/demo-family/deliverables/validation_plan.md",
        "voice": "План задаёт сравнение пилота с контрольной группой, метрику, период наблюдения и нежелательные последствия. Сначала проверяется, можно ли корректно отправить уведомление и выполнить операцию. Полезный результат для связи требует более длинного наблюдения. Если базы для надёжной оценки не хватает, решение — продолжить наблюдение или изменить проверку, а не выдавать слабый сигнал за доказательство эффекта.",
    },
    {
        "title": "Новое основание — пересмотр, а не переписывание",
        "subtitle": "Сценарий новых данных показывает затронутые выводы и расчёты",
        "bullets": ["Новые сведения проходят через impact", "Пересчёты показывают «было → стало»", "Принятое решение остаётся неизменным до нового решения человека"],
        "image": "docs/screenshots/impact.png",
        "voice": "После решения работа продолжается. Сценарий новых данных создаёт копию демо-проекта, регистрирует новое основание и показывает, какие расчёты и утверждения затронуты. Изменения выводятся как было и стало. Принятое решение не переписывается задним числом: оно помечается для пересмотра, а руководитель подтверждает его или принимает новое решение.",
    },
    {
        "title": "Прозрачность и ограничения",
        "subtitle": "Что проверено, что остаётся на стороне команды",
        "bullets": ["В репозитории есть инструкция запуска, база знаний и демо", "validate и check all проходят без ошибок", "Сквозной запуск в Cursor и GigaCode здесь не выполнялся"],
        "image": "docs/screenshots/tests.png",
        "voice": "Репозиторий содержит инструкции, базу знаний, CLI, демо-проект, PDF-описание и тесты критических инвариантов. В текущей среде проверены validate и check all для демо; отчёт о проверках прямо отмечает, что запуск внутри Cursor и GigaCode не выполнялся. Оценка сравнения с обычным чатом также описана с преимуществами и проигрышами агента. Это учебный пример, а не доказательство реального коммерческого эффекта.",
    },
]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def speak_wav(text: str, path: Path) -> None:
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voices = voice.GetVoices()
    russian = next((v for v in voices if "Russian" in v.GetDescription() or "Irina" in v.GetDescription()), None)
    if russian is None:
        raise RuntimeError("A Russian SAPI voice is required")
    voice.Voice = russian
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(path), 3, False)
    voice.AudioOutputStream = stream
    voice.Speak(text)
    voice.WaitUntilDone(-1)
    stream.Close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/STRATEGY-DEMO-NARRATED.mp4"))
    parser.add_argument("--ffmpeg", default=r"C:\Program Files\Live2D Cubism 5.0\tools\ffmpeg\ffmpeg.exe")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 34)
    bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 48)
    small = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 23)
    voice_paths: list[Path] = []
    durations: list[int] = []

    with tempfile.TemporaryDirectory(prefix="strateg-video-") as td:
        tmp = Path(td)
        # Render narration clips first; each scene remains visible through its narration.
        for i, scene in enumerate(SCENES):
            wav_path = tmp / f"voice-{i:02}.wav"
            speak_wav(scene["voice"], wav_path)
            voice_paths.append(wav_path)
            with wave.open(str(wav_path), "rb") as wav:
                durations.append(math.ceil(wav.getnframes() / wav.getframerate()) + 2)

        silent_video = tmp / "silent.mp4"
        writer = cv2.VideoWriter(str(silent_video), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
        if not writer.isOpened():
            raise RuntimeError("Could not open MP4 video writer")

        for i, scene in enumerate(SCENES):
            canvas = Image.new("RGB", SIZE, (19, 24, 34))
            draw = ImageDraw.Draw(canvas)
            draw.text((76, 42), scene["title"], font=bold, fill=(250, 250, 252))
            draw.text((80, 112), scene["subtitle"], font=font, fill=(177, 198, 220))
            y = 220
            for bullet in scene["bullets"]:
                draw.ellipse((88, y + 13, 102, y + 27), fill=(69, 180, 148))
                for line in wrap(draw, bullet, font, 800):
                    draw.text((124, y), line, font=font, fill=(236, 240, 247))
                    y += 48
                y += 34
            image_path = ROOT / scene["image"]
            if image_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                img = Image.open(image_path).convert("RGB")
                bounds = (970, 205, 1845, 945)
                scale = min((bounds[2] - bounds[0]) / img.width, (bounds[3] - bounds[1]) / img.height)
                size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(size, Image.Resampling.LANCZOS)
                x, yy = bounds[0] + (bounds[2] - bounds[0] - size[0]) // 2, bounds[1] + (bounds[3] - bounds[1] - size[1]) // 2
                canvas.paste(img, (x, yy))
            else:
                # The source artifact is Markdown: show its actual section names and a reference label.
                draw.rounded_rectangle((1010, 280, 1810, 860), radius=24, fill=(32, 42, 58), outline=(67, 91, 121), width=3)
                draw.text((1060, 330), "Материал проекта", font=bold, fill=(250, 250, 252))
                draw.text((1060, 410), image_path.relative_to(ROOT).as_posix(), font=small, fill=(177, 198, 220))
                source = image_path.read_text(encoding="utf-8", errors="replace")
                headings = [line.lstrip("# ") for line in source.splitlines() if line.startswith("#")][:8]
                yy = 490
                for heading in headings:
                    draw.text((1060, yy), "• " + heading[:58], font=small, fill=(236, 240, 247))
                    yy += 42
            draw.text((80, 1014), f"{i+1:02d} / {len(SCENES):02d}     demo-family", font=small, fill=(132, 151, 174))
            frame = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
            for _ in range(FPS * durations[i]):
                writer.write(frame)
        writer.release()

        audio = tmp / "voice.wav"
        with wave.open(str(voice_paths[0]), "rb") as first:
            params = first.getparams()
        with wave.open(str(audio), "wb") as combined:
            combined.setparams(params)
            for i, wav_path in enumerate(voice_paths):
                with wave.open(str(wav_path), "rb") as clip:
                    clip_params = clip.getparams()
                    if (clip_params.nchannels, clip_params.sampwidth, clip_params.framerate, clip_params.comptype) != (params.nchannels, params.sampwidth, params.framerate, params.comptype):
                        raise RuntimeError("SAPI produced incompatible audio formats")
                    frames = clip.readframes(clip.getnframes())
                    combined.writeframesraw(frames)
                    with wave.open(str(wav_path), "rb") as duration_check:
                        clip_seconds = duration_check.getnframes() / duration_check.getframerate()
                    pad_frames = durations[i] - clip_seconds
                    silence = b"\x00" * int(pad_frames * params.framerate * params.nchannels * params.sampwidth)
                    combined.writeframesraw(silence)
        subprocess.run([args.ffmpeg, "-y", "-i", str(silent_video), "-i", str(audio), "-c:v", "libopenh264", "-b:v", "1800k", "-c:a", "aac", "-b:a", "128k", "-shortest", str(output)], check=True)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
