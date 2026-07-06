.PHONY: up down restart logs migrate init-models create-migration test clean help

help:
	@echo "RAG 知识库平台 - Makefile"
	@echo ""
	@echo "可用命令:"
	@echo "  make up              启动所有服务"
	@echo "  make down            停止所有服务"
	@echo "  make restart         重启后端和 worker"
	@echo "  make logs            查看后端和 worker 日志"
	@echo "  make migrate         执行数据库迁移"
	@echo "  make create-migration msg=<name>  创建新迁移文件"
	@echo "  make init-models     拉取 Ollama 模型"
	@echo "  make test            运行后端单元测试"
	@echo "  make clean           清理所有容器和数据卷"

up:
	cd deploy && docker-compose up -d

down:
	cd deploy && docker-compose down

restart:
	cd deploy && docker-compose restart backend celery_worker

logs:
	cd deploy && docker-compose logs -f backend celery_worker

migrate:
	cd deploy && docker-compose exec backend alembic upgrade head

create-migration:
	cd deploy && docker-compose exec backend alembic revision --autogenerate -m "$(msg)"

init-models:
	cd deploy && docker-compose exec ollama ollama pull qwen2.5:7b
	cd deploy && docker-compose exec ollama ollama pull nomic-embed-text
	cd deploy && docker-compose exec ollama ollama pull bge-reranker-base

test:
	cd backend && poetry run pytest tests/ -v --cov=app --cov-report=term-missing

clean:
	cd deploy && docker-compose down -v

backend-shell:
	cd deploy && docker-compose exec backend bash
