# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install system dependencies for PyAudio and build tools
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    gcc \
    build-essential \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Update requirements.txt to use a different audio library
RUN sed -i 's/pyaudio/sounddevice/g' requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 8080

# Define environment variable
ENV FLASK_APP=transcribe.py

# Run the application
CMD ["python", "transcribe.py"]
