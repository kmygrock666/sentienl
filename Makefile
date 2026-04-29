PYTHON := ./.venv/bin/python
PIP    := ./.venv/bin/pip

.PHONY: help install install-dev format lint type-check test test-cov \
        init-db docker-up docker-down docker-build clean

help: ## 顯示可用指令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# 環境
# ---------------------------------------------------------------------------
install: ## 安裝生產依賴
	$(PIP) install -r requirements.txt

install-dev: ## 安裝開發依賴（含 pre-commit hooks）
	$(PIP) install -r requirements-dev.txt
	./.venv/bin/pre-commit install

# ---------------------------------------------------------------------------
# 程式碼品質
# ---------------------------------------------------------------------------
format: ## 格式化程式碼（black + isort）
	./.venv/bin/black sentinel tests scripts
	./.venv/bin/isort sentinel tests scripts

lint: ## Linting（ruff）
	./.venv/bin/ruff check sentinel tests

type-check: ## 靜態型別檢查（mypy）
	./.venv/bin/mypy sentinel

check: format lint type-check ## 執行所有程式碼品質檢查

# ---------------------------------------------------------------------------
# 測試
# ---------------------------------------------------------------------------
test: ## 執行測試
	$(PYTHON) -m pytest -q

test-cov: ## 執行測試並產生覆蓋率報告
	$(PYTHON) -m pytest --cov=sentinel --cov-report=term-missing --cov-report=html

# ---------------------------------------------------------------------------
# 資料庫
# ---------------------------------------------------------------------------
init-db: ## 初始化本地 SQLite 資料庫
	$(PYTHON) -m sentinel init-db \
		--database-url sqlite:///data/db/sentinel.db

migrate: ## 執行 Alembic 遷移（需設定 TS_DATABASE_URL）
	./.venv/bin/alembic upgrade head

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
docker-build: ## 建置 Docker 映像
	docker compose build

docker-up: ## 啟動本地開發環境（PostgreSQL + app）
	docker compose up -d

docker-down: ## 停止本地開發環境
	docker compose down

docker-logs: ## 查看 app 容器日誌
	docker compose logs -f app

# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------
clean: ## 清除暫存檔
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
