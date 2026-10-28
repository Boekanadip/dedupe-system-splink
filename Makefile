.PHONY: help setup start stop train predict api ui monitor test clean docker-build docker-up docker-down

help:
	@echo "CRM Entity Resolution System"
	@echo ""
	@echo "Usage:"
	@echo "  make setup      - Setup local Python environment"
	@echo "  make start      - Start PostgreSQL via docker-compose"
	@echo "  make stop       - Stop all services"
	@echo "  make train      - Train Splink model"
	@echo "  make predict    - Run batch prediction"
	@echo "  make api        - Start FastAPI server"
	@echo "  make ui         - Start Streamlit UI"
	@echo "  make monitor    - Run metrics collection"
	@echo "  make test       - Run all tests"
	@echo "  make clean      - Clean up temporary files"
	@echo "  make docker-up  - Start all services with Docker Compose"
	@echo "  make docker-down- Stop all Docker services"

setup:
	python -m venv .venv
	.venv\Scripts\pip install --upgrade pip
	.venv\Scripts\pip install -r requirements.txt
	.venv\Scripts\pip install -r requirements-dev.txt

start:
	docker-compose up -d

stop:
	docker-compose down

train:
	.venv\Scripts\python src\splink_model.py

predict:
	.venv\Scripts\python scripts\batch_predict.py

api:
	.venv\Scripts\python api\app.py

ui:
	.venv\Scripts\streamlit run ui\app.py --server.port 8501

monitor:
	.venv\Scripts\python monitor\metrics.py

test:
	.venv\Scripts\pytest tests\ -v

clean:
	rmdir /s /q __pycache__ .pytest_cache 2>nul
	del /q outputs\*.tmp 2>nul
	del /q outputs\.pipeline_running 2>nul

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down