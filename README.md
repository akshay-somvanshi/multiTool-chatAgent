# multiTool-chatAgent

A conversational AI agent built with Langchain and Google Vertex AI, designed to interact with multiple Google Cloud services as specialized tools. This project provides a framework that can leverage various Google Cloud capabilities to answer complex queries, process documents, and retrieve information from diverse sources.

## Features

*   **Conversational AI Core:** Powered by Google Vertex AI's Generative AI models (e.g., Gemini), enabling natural and dynamic interactions.
*   **Dynamic Model Selection:** Optimizes performance and cost by dynamically switching between basic and advanced Gemini models based on conversation complexity.
*   **Google Search Integration:** Performs real-time web searches using the Google Search API to fetch up-to-date information.
*   **Vertex AI Search (Discovery Engine) Integration:** Queries internal data stores and knowledge bases configured within Google Cloud's Discovery Engine for tailored information retrieval.
*   **Document AI Integration:** Extracts structured and unstructured text content from PDF documents, enabling intelligent processing of reports, invoices, and other document types.
*   **Chat History & Context Management:** Utilizes Google Firestore to persist chat history and manage user-specific context across sessions.
*   **FastAPI Web Interface:** Provides a lightweight and high-performance web application built with FastAPI, making it easy to expose the agent via an API.
*   **Docker Support:** Containerized with Docker for consistent deployment across different environments.

## Getting Started

Follow these steps to get your multiTool-chatAgent up and running.

### Prerequisites

*   **Google Cloud Project:** With the following APIs enabled:
    *   Vertex AI API
    *   Discovery Engine API
    *   Document AI API
    *   Firestore API
*   **Google Cloud SDK (`gcloud` CLI):** Installed and authenticated on your machine.
    *   Run `gcloud auth application-default login` to authenticate.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/akshay-somvanshi/multiTool-chatAgent.git
    cd multiTool-chatAgent
    ```

2.  **Set up Environment Variables:**
    Create a `.env` file in the root of the project and populate it with your Google Cloud project details and service IDs:

    ```ini
    GOOGLE_PROJECT_ID="your-gcp-project-id"
    GOOGLE_LOCATION="your-gcp-region" # e.g., europe-west1, us-central1
    VERTEX_ENGINE_ID="your-discovery-engine-id"
    DOCUMENT_AI_ID="your-document-ai-processor-id"
    ```
    *   You can find your `GOOGLE_PROJECT_ID` in the Google Cloud Console.
    *   `GOOGLE_LOCATION` should be a region where Vertex AI and other services are available.
    *   `VERTEX_ENGINE_ID` refers to the ID of your search application in Discovery Engine.
    *   `DOCUMENT_AI_ID` is the processor ID for your Document AI instance.

3.  **Install Python Dependencies:**
    ```bash
    cd ChatAgent
    pip install -r requirements.txt
    pip install -e .
    ```

### Running the Application

#### Locally (without Docker)

From the `ChatAgent` directory:

```bash
fastapi dev chat_agent/app.py
```
The application will be accessible at `http://127.0.0.1:8000`.

#### Using Docker

1.  **Build the Docker image:**
    ```bash
    docker build -t multitool-chatagent .
    ```

2.  **Run the Docker container:**
    ```bash
    docker run -p 8080:8080 --env-file ./.env multitool-chatagent
    ```
    The `--env-file ./.env` flag ensures your environment variables are passed into the container.
    The application will be accessible at `http://localhost:8080`.

## Project Structure

```
ChatAgent/
├── chat_agent/           # Main application package
│   ├── core/             # Core logic and exceptions
│   ├── data/             # Planning questions and data files
│   ├── prompts/          # System instructions and prompts
│   ├── __init__.py
│   ├── agent.py          # Core Langchain agent logic
│   ├── app.py            # FastAPI application definition
│   ├── classifier.py     # Intent classification logic
│   ├── firestore.py      # Firestore integration
│   └── tools.py          # Tool definitions
├── test/                 # Test suite
│   └── test_async.py
├── setup.py              # Installation script for editable mode
├── pyproject.toml        # Package configuration and dependencies
├── requirements.txt      # Legacy requirements file
└── Dockerfile            # Container definition
```

### Troubleshooting
If you encounter `ModuleNotFoundError: No module named 'chat_agent'` or permission errors during `pip install`, use `PYTHONPATH` to run your application without installation:

```bash
# From the ChatAgent directory
export PYTHONPATH=$PYTHONPATH:.
fastapi dev chat_agent/app.py
```

Or run as a one-liner:
```bash
PYTHONPATH=. fastapi dev chat_agent/app.py
```
