.PHONY: up down restart logs migrate init-models build clean help backend-shell backup

help:
	@echo "RAG 知识库平台 - Makefile"
	@echo ""
	@echo "可用命令:"
	@echo "  make build           构建所有镜像"
	@echo "  make up              启动所有服务"
	@echo "  make down            停止所有服务"
	@echo "  make restart         重启后端和 worker"
	@echo "  make logs            查看后端和 worker 日志"
	@echo "  make migrate         执行数据库迁移"
	@echo "  make create-migration msg=<name>  创建新迁移文件"
	@echo "  make init-models     拉取 Ollama 模型"
	@echo "  make backend-shell   进入后端容器"
	@echo "  make clean           清理所有容器和数据卷"
	@echo "  make backup          执行数据库备份 (make backup ARGS=--dry-run 试运行)"

build:
	docker compose -f deploy/docker-compose.yml build

up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

restart:
	docker compose -f deploy/docker-compose.yml restart backend celery_worker

logs:
	docker compose -f deploy/docker-compose.yml logs -f backend celery_worker

migrate:
	docker compose -f deploy/docker-compose.yml exec backend alembic upgrade head

create-migration:
	docker compose -f deploy/docker-compose.yml exec backend alembic revision --autogenerate -m "$(msg)"

init-models:
	docker compose -f deploy/docker-compose.yml exec ollama ollama pull qwen2.5:7b
	docker compose -f deploy/docker-compose.yml exec ollama ollama pull bge-m3
	docker compose -f deploy/docker-compose.yml exec ollama ollama pull bge-reranker-base

backend-shell:
	docker compose -f deploy/docker-compose.yml exec backend bash

clean:
	docker compose -f deploy/docker-compose.yml down -v

backup:
	@echo "运行数据库备份..."
	@if [ -f deploy/.env ]; then set -a && . ./deploy/.env && set +a; fi; \
	bash deploy/scripts/backup_db.sh $(ARGS)