2. Choose your provider
Local (Ollama, 100% offline):

bash
ollama pull llama3.2
python cli.py --provider ollama
BYOK (OpenAI, Anthropic, DeepSeek):

bash
python cli.py --provider anthropic
python cli.py --provider deepseek
3. Run
bash
python cli.py                    # interactive REPL
python cli.py --task "fix bug"   # one-shot task
🧩 Supported Providers
Provider	Type	Setup
Ollama	Local	ollama pull llama3.2
Anthropic	Cloud	ANTHROPIC_API_KEY
OpenAI	Cloud	OPENAI_API_KEY
DeepSeek	Cloud	DEEPSEEK_API_KEY
🔌 Interfaces
1. CLI
bash
python cli.py
python cli.py --task "refactor config"
2. REST API
bash
python -m neo_code.connector.server
# Open http://127.0.0.1:8000/docs
3. MCP Server (Claude Desktop)
Config: %APPDATA%\Claude\claude_desktop_config.json

json
{
  "mcpServers": {
    "neo": {
      "command": "python",
      "args": ["-m", "neo_code.connector.mcp_server"],
      "env": {"PYTHONPATH": "C:\\path\\to\\project"}
    }
  }
}
4. MCP Client (remote servers)
Config: ~/.neo/mcp.json

json
{
  "mcpServers": {
    "huggingface": {
      "url": "https://huggingface.co/mcp",
      "transport": "streamable_http"
    }
  }
}
🛠️ 52 Built-in Tools
Filesystem (13): read_file, write_file, edit_file, delete_file, list_directory, search_files, execute_command, run_tests, git_status, git_diff, git_log, project_scan, project_info

Web (3): web_search, fetch_url, datetime

SSH (8): ssh_list_connections, ssh_add_connection, ssh_connect, ssh_disconnect, ssh_exec, ssh_upload, ssh_download, ssh_list_remote

REST Client (6): api_add_endpoint, api_list_endpoints, api_remove_endpoint, api_get, api_post, api_request

MCP Client (4): mcp_list_servers, mcp_list_tools, mcp_connect, mcp_call_tool

Orchestration (1): neo_orchestrate

Self-Improvement (3): self_improve, generalize, autonomy

Planning (5): plan, delegate, list_agents, delegate_task, recall

Memory (4): remember, recall, project_context, session_history

Evaluation (2): evaluate_task, record_improvement

🎯 Examples
Fix a bug
bash
python cli.py --task "find and fix the bug in auth"
Deploy via SSH
bash
python cli.py --task "deploy to prod via SSH"
Orchestrate tasks
bash
python cli.py --task "orchestrate: 1) run tests 2) fix 3) commit"
REST API
bash
curl -X POST http://127.0.0.1:8000/task \
  -H "Content-Type: application/json" \
  -d '{"task": "count files", "auto_approve": true}'
🏗️ Architecture
text
neo_code/
├── cli.py              # Entry point
├── core/               # Agent engine
├── connector/          # REST + MCP (server/client)
├── providers/          # Ollama, Anthropic, OpenAI, DeepSeek
├── tools/              # 52 tools
├── skills/             # Skill definitions
└── ui/                 # Terminal UI
🔐 Privacy & Security
Ollama: 100% offline

BYOK: Direct connection

SSH passwords: Windows Credential Manager

API keys: ~/.neo/config.json (never in code)

Approval gate: every dangerous op requires confirmation

🧠 Engineering Loop
text
UNDERSTAND → INSPECT → PLAN → EXECUTE → TEST → VERIFY → REPORT
📦 Requirements
Python 3.11+

requests, anthropic, openai, rich

fastapi, uvicorn (REST)

mcp>=1.20 (MCP)

paramiko, keyring (SSH)

⚖️ License
Source Available — see LICENSE.