FROM python:3.12-slim

WORKDIR /app

# Copy application code
COPY . .

# Install required libraries
RUN pip install --no-cache-dir -r requirements.txt

# Container listens to port 8080
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8080/ || exit 1

# --host 0.0.0.0: make app listen/accessible on all network interfaces
# --port 8080: app listens on container port 8080
CMD ["uvicorn", "chat_agent.app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "debug"]