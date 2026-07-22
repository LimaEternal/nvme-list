#!/usr/bin/env python3

import sys
import re
import html
from pathlib import Path
from html.parser import HTMLParser


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Эти теги и всё их содержимое игнорируем.
IGNORED_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "template",
    "head",
    "iframe",
}

# Элементы интерфейса, которые нам не нужны.
UI_PHRASES = {
    "Копировать",
    "Скопировано",
    "Изменить",
    "Поделиться ссылкой",
    "Хороший ответ",
    "Плохой ответ",
    "Экономит время",
    "Полезный",
    "Подробный",
    "Неверный",
    "Недопустимый",
    "Не работает",
    "Отправить",
    "Спасибо, что сообщили нам.",
    "Показать все",
}


# ============================================================
# УТИЛИТЫ
# ============================================================

def decode(text):
    """
    Декодирует HTML-сущности.
    """

    for _ in range(3):
        new_text = html.unescape(text)

        if new_text == text:
            break

        text = new_text

    return text


def normalize_text(text):
    """
    Аккуратно чистит текст.
    """

    text = decode(text)

    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Убираем пробелы перед переносом.
    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text
    )

    # Убираем пробелы после переноса.
    text = re.sub(
        r"\n[ \t]+",
        "\n",
        text
    )

    # Более 2 пустых строк подряд не нужны.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# СООБЩЕНИЕ
# ============================================================

class Message:
    def __init__(self, role, text=""):
        self.role = role
        self.text = text


# ============================================================
# HTML PARSER
# ============================================================

class ChatParser(HTMLParser):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.messages = []

        # Текущее сообщение.
        self.current = None

        # Стек открытых тегов.
        self.tag_stack = []

        # Игнорируем ли текущий блок.
        self.ignore_depth = 0

        # Сейчас внутри <pre>?
        self.in_pre = False

        # Сейчас внутри <code>?
        self.in_code = False

        # Буфер текста текущего сообщения.
        self.buffer = []

        # Для определения пользовательского сообщения.
        self.pending_user = None

        # Сколько HTML-уровней прошло после запроса.
        self.user_depth = None

        # Последний найденный пользовательский запрос.
        self.last_user_text = None

    # --------------------------------------------------------
    # ВСПОМОГАТЕЛЬНЫЕ
    # --------------------------------------------------------

    def is_user_label(self, attrs):
        """
        Проверяет aria-label.

        Google использует примерно:

        aria-label="Копировать запрос ..."
        aria-label="Изменить запрос ..."
        """

        attrs = dict(attrs)

        label = attrs.get("aria-label", "")

        if not label:
            return None

        label = decode(label)

        match = re.match(
            r"^(?:Копировать|Изменить)\s+запрос\s+(.+)$",
            label,
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            return None

        text = match.group(1).strip()

        # Иногда запрос находится в кавычках.
        if (
            len(text) >= 2
            and text[0] in "\"'"
            and text[-1] == text[0]
        ):
            text = text[1:-1]

        return normalize_text(text)

    def is_ui_element(self, attrs):

        attrs = dict(attrs)

        label = attrs.get(
            "aria-label",
            ""
        )

        label = decode(label)

        for phrase in UI_PHRASES:

            if phrase.lower() in label.lower():
                return True

        return False

    def start_message(self, role, text):

        if self.current is not None:
            self.finish_message()

        self.current = Message(
            role=role,
            text=text
        )

        self.buffer = []

    def finish_message(self):

        if self.current is None:
            return

        text = "".join(
            self.buffer
        )

        text = normalize_text(text)

        if text:

            self.current.text = text

            self.messages.append(
                self.current
            )

        self.current = None
        self.buffer = []

    # --------------------------------------------------------
    # START TAG
    # --------------------------------------------------------

    def handle_starttag(self, tag, attrs):

        tag = tag.lower()

        self.tag_stack.append(tag)

        # Игнорируем технические блоки.
        if tag in IGNORED_TAGS:

            self.ignore_depth += 1

            return

        if self.ignore_depth:
            return

        # ----------------------------------------------------
        # ИЩЕМ ПОЛЬЗОВАТЕЛЬСКИЙ ЗАПРОС
        # ----------------------------------------------------

        user_text = self.is_user_label(
            attrs
        )

        if user_text:

            # Если это новый запрос,
            # завершаем предыдущий ответ.
            self.finish_message()

            self.start_message(
                "user",
                user_text
            )

            self.last_user_text = user_text

            return

        # ----------------------------------------------------
        # CODE / PRE
        # ----------------------------------------------------

        if tag == "pre":

            self.in_pre = True

            if self.current:

                self.buffer.append(
                    "\n\n```text\n"
                )

            return

        if tag == "code":

            self.in_code = True

            return

        # ----------------------------------------------------
        # БЛОЧНЫЕ ЭЛЕМЕНТЫ
        # ----------------------------------------------------

        if tag in {
            "div",
            "p",
            "section",
            "article",
            "li",
            "blockquote",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:

            if self.current:

                if self.buffer:
                    self.buffer.append(
                        "\n"
                    )

    # --------------------------------------------------------
    # END TAG
    # --------------------------------------------------------

    def handle_endtag(self, tag):

        tag = tag.lower()

        if tag in IGNORED_TAGS:

            if self.ignore_depth > 0:
                self.ignore_depth -= 1

        if self.ignore_depth:
            return

        if tag == "pre":

            if self.current:

                self.buffer.append(
                    "\n```\n\n"
                )

            self.in_pre = False

        elif tag == "code":

            self.in_code = False

        elif tag in {
            "br",
            "p",
            "div",
            "section",
            "article",
            "li",
            "blockquote",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:

            if self.current:

                self.buffer.append(
                    "\n"
                )

        # Удаляем тег из стека.
        if self.tag_stack:

            # В нормальном HTML последний тег совпадает.
            if self.tag_stack[-1] == tag:

                self.tag_stack.pop()

            else:

                # На случай кривого HTML.
                try:

                    index = (
                        len(self.tag_stack)
                        - 1
                        - self.tag_stack[::-1].index(tag)
                    )

                    del self.tag_stack[index]

                except ValueError:
                    pass

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    def handle_data(self, data):

        if self.ignore_depth:
            return

        if self.current is None:
            return

        if not data:
            return

        # Если это обычный текст.
        self.buffer.append(data)

    # --------------------------------------------------------
    # ENTITY
    # --------------------------------------------------------

    def handle_entityref(self, name):

        if self.current is None:
            return

        self.buffer.append(
            html.unescape(
                f"&{name};"
            )
        )

    def handle_charref(self, name):

        if self.current is None:
            return

        self.buffer.append(
            html.unescape(
                f"&#{name};"
            )
        )

    # --------------------------------------------------------
    # COMMENT
    # --------------------------------------------------------

    def handle_comment(self, data):
        pass

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    def close(self):

        super().close()

        self.finish_message()


# ============================================================
# ПОСТОБРАБОТКА
# ============================================================

def clean_messages(messages):

    result = []

    previous = None

    for message in messages:

        text = normalize_text(
            message.text
        )

        if not text:
            continue

        # Удаляем чистые UI-строки.
        lines = []

        for line in text.splitlines():

            stripped = line.strip()

            if stripped in UI_PHRASES:
                continue

            lines.append(line)

        text = "\n".join(
            lines
        )

        text = normalize_text(
            text
        )

        if not text:
            continue

        # Убираем дубли.
        key = (
            message.role,
            text
        )

        if key == previous:
            continue

        result.append(
            Message(
                message.role,
                text
            )
        )

        previous = key

    return result


# ============================================================
# ВАЖНЫЙ ЭТАП:
# УДАЛЯЕМ ДУБЛИКАТЫ ПОЛЬЗОВАТЕЛЬСКИХ СООБЩЕНИЙ
# ============================================================

def merge_consecutive_messages(messages):

    result = []

    for message in messages:

        # Если подряд идут два сообщения одного типа,
        # обычно это означает, что HTML-разметка
        # разбила одно сообщение на несколько частей.
        if (
            result
            and result[-1].role == message.role
        ):

            result[-1].text += (
                "\n\n"
                + message.text
            )

        else:

            result.append(
                Message(
                    message.role,
                    message.text
                )
            )

    return result


# ============================================================
# MARKDOWN
# ============================================================

def to_markdown(messages, source_name):

    output = []

    output.append(
        "# История диалога"
    )

    output.append("")

    output.append(
        f"> Источник: `{source_name}`"
    )

    output.append("")

    for message in messages:

        if message.role == "user":

            output.append(
                "## Пользователь"
            )

        else:

            output.append(
                "## Ассистент"
            )

        output.append("")

        output.append(
            message.text
        )

        output.append("")

        output.append(
            "---"
        )

        output.append("")

    return "\n".join(
        output
    ).rstrip() + "\n"


# ============================================================
# MAIN
# ============================================================

def main():

    if len(sys.argv) < 2:

        print(
            "Использование:\n"
            "\n"
            "  python clean_html_chat.py input.htm\n"
            "\n"
            "Или:\n"
            "\n"
            "  python clean_html_chat.py input.htm output.md"
        )

        sys.exit(1)

    input_path = Path(
        sys.argv[1]
    )

    if not input_path.exists():

        print(
            f"Ошибка: файл не найден:\n"
            f"{input_path}"
        )

        sys.exit(1)

    # Если имя выходного файла не задано,
    # создаём его рядом с HTML.
    if len(sys.argv) >= 3:

        output_path = Path(
            sys.argv[2]
        )

    else:

        output_path = input_path.with_name(
            input_path.stem
            + "_clean.md"
        )

    print(
        f"[1/5] Читаю {input_path}"
    )

    html_text = input_path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    print(
        f"      Размер: "
        f"{len(html_text):,} символов"
    )

    print(
        "[2/5] Парсю HTML..."
    )

    parser = ChatParser()

    parser.feed(
        html_text
    )

    parser.close()

    print(
        f"      Найдено элементов: "
        f"{len(parser.messages)}"
    )

    print(
        "[3/5] Очищаю сообщения..."
    )

    messages = clean_messages(
        parser.messages
    )

    print(
        "[4/5] Объединяю структуру диалога..."
    )

    messages = merge_consecutive_messages(
        messages
    )

    users = sum(
        1
        for m in messages
        if m.role == "user"
    )

    assistants = sum(
        1
        for m in messages
        if m.role == "assistant"
    )

    print(
        f"      Пользователь: "
        f"{users}"
    )

    print(
        f"      Ассистент: "
        f"{assistants}"
    )

    print(
        "[5/5] Записываю Markdown..."
    )

    markdown = to_markdown(
        messages,
        input_path.name
    )

    output_path.write_text(
        markdown,
        encoding="utf-8"
    )

    print()
    print(
        "Готово."
    )

    print(
        f"Файл: {output_path}"
    )

    print(
        f"Размер: "
        f"{len(markdown):,} символов"
    )

    if len(html_text):

        reduction = (
            1
            - len(markdown)
            / len(html_text)
        ) * 100

        print(
            f"Сжатие: "
            f"{reduction:.1f}%"
        )


if __name__ == "__main__":
    main()