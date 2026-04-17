# Local MCP File Server (ChatGPT Access)

## Purpose
Expose local filesystem (E:\Programming) so ChatGPT can read project files.

This is REQUIRED for:
- debugging Job Hunter
- inspecting logs
- reviewing prompts and filters
- avoiding hallucination

---

## Start Server

```bash
cd E:\Programming
python mcp_fileserver.py