# Use the official Microsoft image that already has Python and Browsers
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

# Set the working directory
WORKDIR /app

# Copy the requirements file into the image
COPY requirements.txt .

# Install the Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: No 'playwright install' command is needed!
# The browsers are already baked into this specific base image.
COPY . .