# Use an official Python slim image as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependency files to the working directory
# We'll generate a requirements.txt from pyproject.toml for a simpler build process.
COPY pyproject.toml ./

# Install dependencies
# We use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir "python-dotenv>=1.1.1" "streamlit>=1.46.1" "supabase>=2.16.0" "pandas>=2.0.0"

# Copy the rest of the application code into the container
COPY . .

# Expose the port that Streamlit runs on
EXPOSE 8501

# Define the command to run the application
# We use --server.enableCORS=false to avoid potential cross-origin issues in some environments
# and --server.runOnSave=true for a better development experience.
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
