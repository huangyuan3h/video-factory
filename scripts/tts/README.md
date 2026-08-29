# TTS Scripts

Ported from Fae-v2.

- `spark-voices.json` — voice library for local Spark-TTS (hot-reloaded by server).
  Add a voice: `POST /api/tts-settings/voices/register` with `voice_id`, `transcript`, `file`.
- Local server is external: run `bash scripts/tts/run.sh` (Qwen3-TTS :8883) or `bash scripts/tts/run-spark.sh` (:8890) from Fae-v2, or any OpenAI-compatible TTS Docker image.

Set env to enable:
```bash
VLLM_TTS_URL=http://127.0.0.1:8883/v1        # Qwen/Cosy
# or
VLLM_TTS_HQ_URL=http://127.0.0.1:8890/v1    # Spark HQ — takes precedence
```
