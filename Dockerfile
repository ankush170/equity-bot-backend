# Use an official lightweight Python image.
FROM python:3.9-slim

# Set the working directory in the container.
WORKDIR /app

# Copy the requirements file and install dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code.
COPY . .

# Expose the port that your FastAPI app will run on.
EXPOSE 8000

# Define the command to start your app.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]