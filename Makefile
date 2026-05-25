.PHONY: help up down restart logs ps shell test test-integration fmt lint type migrate revision build

# Default: help göster
help:
	@echo "AI NVR — Make hedefleri"
	@echo ""
	@echo "Docker:"
	@echo "  make up               — Tüm container'ları başlat"
	@echo "  make down             — Tüm container'ları durdur"
	@echo "  make restart          — Restart"
	@echo "  make build            — Bridge image'ını yeniden build et"
	@echo "  make logs             — Tüm logları izle"
	@echo "  make ps               — Container durumları"
	@echo "  make shell            — Bridge container'ına bash"
	@echo ""
	@echo "Development (local, uv gerekli):"
	@echo "  make test             — Unit testleri çalıştır"
	@echo "  make test-integration — Integration testleri (postgres/mqtt gerekli)"
	@echo "  make fmt              — ruff format"
	@echo "  make lint             — ruff check"
	@echo "  make type             — mypy"
	@echo ""
	@echo "Migrations:"
	@echo "  make migrate          — Alembic upgrade head"
	@echo "  make revision NAME=x  — Yeni migrasyon oluştur"

up:
	docker compose up -d
	@echo ""
	@echo "Servisler başlatıldı. 'make ps' ile durumu kontrol et."

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build bridge

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

shell:
	docker compose exec bridge /bin/bash

test:
	cd bridge && uv run pytest -v -m "not integration"

test-integration:
	cd bridge && uv run pytest -v -m "integration"

fmt:
	cd bridge && uv run ruff format .

lint:
	cd bridge && uv run ruff check .

type:
	cd bridge && uv run mypy bridge

migrate:
	docker compose exec bridge alembic upgrade head

revision:
	@if [ -z "$(NAME)" ]; then echo "Kullanım: make revision NAME=migration_adi"; exit 1; fi
	docker compose exec bridge alembic revision -m "$(NAME)"
