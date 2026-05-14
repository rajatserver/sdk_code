# Use an official lightweight Python image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy only requirements first (to leverage Docker caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port 8080 (Cloud Run default port)
EXPOSE 8080

# Command to run the application using Gunicorn for better performance
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "8", "--timeout", "900", "--graceful-timeout", "120", "--keep-alive", "75", "-b", "0.0.0.0:8080", "akeneo_58254f73-f340-4b5d-a0dd-f7c7679ea78b:app"]
