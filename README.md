# Web Crawler Knowledge App

> Crawl web content, turn it into searchable knowledge, and query it through a semantic retrieval workflow.

This project explores the core building blocks behind a web-to-knowledge pipeline: collecting web pages, extracting useful content, generating embeddings, storing vectors, and exposing the resulting knowledge through an application interface.

## ✨ Highlights

- 🕷️ Web page crawling and content extraction
- 🧹 Content processing for downstream retrieval
- 🧠 Sentence-transformer embeddings
- 🔎 ChromaDB vector search
- ⚡ FastAPI backend
- 🔐 JWT-based authentication support
- 💻 Separate frontend and backend applications

## 🏗️ Architecture

```text
             URL / Web Page
                    │
                    ▼
          ┌───────────────────┐
          │ Crawler / Parser  │
          │ Requests + BS4    │
          └─────────┬─────────┘
                    │
                    ▼
             Cleaned Content
                    │
                    ▼
          Sentence Transformers
                    │
                    ▼
               ChromaDB
                    │
                    ▼
             Semantic Search
                    │
                    ▼
              FastAPI API
                    │
                    ▼
               Frontend UI
```

## 🛠️ Tech Stack

**Backend**
- Python
- FastAPI
- Uvicorn
- Requests
- BeautifulSoup4
- Pydantic Settings

**AI / Retrieval**
- ChromaDB
- Sentence Transformers

**Documents & Security**
- pypdf
- JWT
- Passlib / bcrypt

**Frontend**
- Dedicated frontend application in `/frontend`

## 📁 Project Structure

```text
web_crawler_knowledge_app/
├── backend/
│   ├── app/
│   └── requirements.txt
├── frontend/
├── .gitignore
└── README.md
```

## 🚀 Getting Started

### Backend

```bash
git clone https://github.com/krishTheCoderBoy/web_crawler_knowledge_app.git
cd web_crawler_knowledge_app/backend

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Configure the required environment variables and start the FastAPI application with Uvicorn according to the project configuration.

### Frontend

```bash
cd ../frontend
npm install
npm run dev
```

## 🧠 Knowledge Pipeline

```text
Crawl → Extract → Clean → Embed → Store → Retrieve → Answer
```

The interesting part of this project is the transition from unstructured web content to a reusable semantic knowledge layer. It is a foundation that can be extended into RAG assistants, internal knowledge systems, research tools, and domain-specific search applications.

## 🧭 Future Improvements

- [ ] Background crawling jobs
- [ ] Crawl progress tracking
- [ ] Better duplicate detection
- [ ] Metadata-aware retrieval
- [ ] RAG answer generation
- [ ] Source citations in responses
- [ ] Scheduled re-crawling

## 👨‍💻 Author

**Krishnendu Dey** — AI / GenAI & Full-Stack Developer

---

Built while exploring practical web crawling, embeddings, vector search, and RAG architectures.
