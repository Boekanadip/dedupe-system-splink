.PHONY: help start stop clean train predict api ui monitor setup

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
	@echo "  make clean      - Clean up temporary files"

setup:
	python -m venv .venv
	.venv\Scripts\pip install --upgrade pip
	.venv\Scripts\pip install -r requirements.txt

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

clean:
	rmdir /s /q __pycache__ .pytest_cache 2>nul
	del /q outputs\*.tmp 2>nul
	del /q outputs\.pipeline_running 2>nul
