# Video Factory

Automated video generation and publishing factory. Automatically fetch content from RSS/News sources, generate short videos with AI, and publish to social media platforms.

## Features

- **Content Sources**: RSS feeds, News APIs, Hot topics (Weibo, Zhihu)
- **AI Integration**: OpenAI-compatible API support (GPT-4o, DeepSeek, etc.)
- **TTS**: Edge-TTS for high-quality Chinese voice synthesis
- **Video Generation**: MoviePy + FFmpeg for video composition
- **Auto Publishing**: Playwright-based automation for Douyin and Xiaohongshu
- **Desktop App**: Tauri-based cross-platform application

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | Next.js 16, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | FastAPI, APScheduler |
| Database | SQLite, Prisma |
| Video | MoviePy, FFmpeg |
| TTS | Edge-TTS |
| AI | OpenAI SDK (compatible mode) |
| Desktop | Tauri 2.x |

## Project Structure

```
video-factory/
├── apps/
│   ├── web/          # Next.js frontend
│   ├── desktop/      # Tauri desktop app
│   └── worker/       # Python worker service
├── packages/
│   ├── shared/       # Shared TypeScript types
│   └── database/     # Prisma schema
└── data/
    ├── assets/       # Local video/image assets
    └── output/       # Generated videos
```

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.11+
- pnpm 9+
- FFmpeg

### Installation

1. Install dependencies:

```bash
# Install Node.js dependencies
pnpm install

# Install Python dependencies
cd apps/worker
pip install -r requirements.txt
playwright install chromium
```

2. Initialize database:

```bash
cd packages/database
pnpm db:push
```

3. Configure environment:

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your API keys
```

### Development

```bash
# Start all services
pnpm dev

# Or start individually:
pnpm web dev      # Next.js frontend
cd apps/worker && python -m uvicorn src.main:app --reload  # Python worker
```

### Desktop App

```bash
# Development
cd apps/desktop
pnpm tauri:dev

# Build release
pnpm tauri:build
```

## Configuration

### AI Provider

Configure OpenAI-compatible API in Settings page:
- Base URL (e.g., `https://api.openai.com/v1`)
- API Key
- Model ID (e.g., `gpt-4o`, `deepseek-chat`)

### TTS Voice

Available Chinese voices:
- `zh-CN-XiaoxiaoNeural` - Female, Natural (Recommended)
- `zh-CN-YunxiNeural` - Male, Sunny
- `zh-CN-YunjianNeural` - Male, News
- `zh-CN-XiaoyiNeural` - Female, Gentle

### Content Sources

1. RSS Feeds - Enter RSS feed URL
2. News API - Configure API key
3. Hot Topics - Select platform (Weibo, Zhihu)

## License

MIT