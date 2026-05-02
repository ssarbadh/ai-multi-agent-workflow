.PHONY: help install dev build test migrate clean

help:
	@echo "AegisOps RAG Service"
	@echo ""
	@echo "Usage:"
	@echo "  make install    - Install dependencies"
	@echo "  make dev        - Run development server"
	@echo "  make build      - Build Docker image"
	@echo "  make up         - Start with Docker Compose"
	@echo "  make down       - Stop containers"
	@echo "  make test       - Run tests"
	@echo "  make index      - Index documents"
	@echo "  make clean      - Clean up"

# Install dependencies
install:
	pip install -r requirements.txt

# Run development server
dev:
	python -m app.main

# Build Docker image
build:
	docker build -t aegisops-rag .

# Start with Docker Compose
up:
	docker-compose up -d

# Stop containers
down:
	docker-compose down

# View logs
logs:
	docker-compose logs -f rag

# Run tests
test:
	pytest -v

# Run tests with coverage
test-cov:
	pytest --cov=app --cov-report=html

# Index documents from directory
index:
	python -m app.scripts.index_documents

# Run evaluation
eval:
	python -m app.scripts.run_eval

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov .coverage

# Download embedding model
download-model:
	python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
