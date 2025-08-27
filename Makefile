.PHONY: help init venv install install-system setup-baresip run test test-system test-api clean sync check-deps

help:
	@echo "Доступные команды:"
	@echo "  make init            - Полная инициализация проекта (venv + зависимости)"
	@echo "  make venv            - Создать виртуальное окружение"
	@echo "  make install         - Установить Python зависимости"
	@echo "  make install-system  - Установить системные пакеты (baresip, ffmpeg)"
	@echo "  make setup-baresip   - Настроить baresip для проекта"
	@echo "  make sync            - Синхронизировать зависимости"
	@echo "  make run             - Запустить сервер"
	@echo "  make run-dev         - Запустить сервер в режиме разработки"
	@echo "  make test            - Запустить все тесты"
	@echo "  make test-system     - Тест подключений (ElevenLabs, SIP)"
	@echo "  make test-api        - Тест API эндпоинтов"
	@echo "  make clean           - Очистить кэш и временные файлы"
	@echo "  make check-deps      - Проверить установленные зависимости"

init: venv install
	@echo "🎉 Проект успешно инициализирован!"
	@echo "📝 Не забудьте проверить файл .env"

venv:
	@if [ ! -d ".venv" ]; then \
		echo "🔧 Создание виртуального окружения..."; \
		uv venv; \
		echo "✅ Виртуальное окружение создано"; \
	else \
		echo "✅ Виртуальное окружение уже существует"; \
	fi

install: venv
	@echo "📦 Установка Python зависимостей..."
	uv pip install -e .
	@echo "✅ Python зависимости установлены"

install-system:
	@echo "🔧 Установка системных пакетов..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		echo "📱 Обнаружена macOS, устанавливаем через Homebrew..."; \
		brew list baresip &>/dev/null || brew install baresip; \
		brew list ffmpeg &>/dev/null || brew install ffmpeg; \
		brew list portaudio &>/dev/null || brew install portaudio; \
	elif [ "$$(uname)" = "Linux" ]; then \
		echo "🐧 Обнаружен Linux, устанавливаем через apt..."; \
		sudo apt-get update; \
		sudo apt-get install -y baresip ffmpeg portaudio19-dev; \
	else \
		echo "⚠️  Неподдерживаемая ОС. Установите baresip и ffmpeg вручную."; \
		exit 1; \
	fi
	@echo "✅ Системные пакеты установлены"

setup-baresip:
	@echo "⚙️  Настройка baresip..."
	@mkdir -p ~/.baresip
	@if [ -f config/baresip/config ]; then \
		cp config/baresip/config ~/.baresip/; \
		echo "✅ Конфигурация baresip скопирована"; \
	fi
	@if [ -f config/baresip/accounts ]; then \
		cp config/baresip/accounts ~/.baresip/; \
		echo "✅ SIP аккаунты настроены"; \
	fi
	@echo "📝 Создание виртуальных аудио устройств..."
	@echo "⚠️  Для macOS: используйте BlackHole или Loopback"
	@echo "⚠️  Для Linux: настройте PulseAudio loopback модули"

sync: venv
	@echo "🔄 Синхронизация зависимостей..."
	uv sync
	@echo "✅ Зависимости синхронизированы"

run:
	@echo "🚀 Запуск сервера..."
	@if [ ! -f .env ]; then \
		echo "❌ Файл .env не найден!"; \
		exit 1; \
	fi
	uv run python -m src.main

run-dev:
	@echo "🚀 Запуск сервера в режиме разработки..."
	@if [ ! -f .env ]; then \
		echo "❌ Файл .env не найден!"; \
		exit 1; \
	fi
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

test: test-system test-api

test-system:
	@echo "🧪 Тестирование системных компонентов..."
	uv run python test_system.py

test-api:
	@echo "🧪 Тестирование API..."
	uv run python test_api.py

clean:
	@echo "🧹 Очистка кэша и временных файлов..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete
	@echo "✅ Очистка завершена"

check-deps:
	@echo "🔍 Проверка установленных зависимостей..."
	@echo ""
	@echo "🐍 Python окружение:"
	@if [ -d ".venv" ]; then \
		echo "✅ Виртуальное окружение найдено"; \
	else \
		echo "❌ Виртуальное окружение не найдено (запустите: make venv)"; \
	fi
	@echo ""
	@echo "📦 Python пакеты:"
	@if [ -d ".venv" ]; then \
		uv pip list 2>/dev/null | grep -E "(fastapi|dishka|aiohttp|uvicorn|pydantic)" || echo "⚠️  Основные пакеты не найдены (запустите: make install)"; \
	else \
		echo "⚠️  Сначала создайте виртуальное окружение"; \
	fi
	@echo ""
	@echo "🔧 Системные пакеты:"
	@command -v baresip >/dev/null 2>&1 && echo "✅ baresip установлен" || echo "❌ baresip не найден"
	@command -v ffmpeg >/dev/null 2>&1 && echo "✅ ffmpeg установлен" || echo "❌ ffmpeg не найден"
	@echo ""
	@echo "🔌 Проверка портов:"
	@lsof -i :8000 >/dev/null 2>&1 && echo "⚠️  Порт 8000 занят" || echo "✅ Порт 8000 свободен"
	@lsof -i :4444 >/dev/null 2>&1 && echo "⚠️  Порт 4444 (baresip) занят" || echo "✅ Порт 4444 свободен"