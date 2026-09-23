#  Neo  Matrix AI Agent

> Wake up, Neo... The Matrix has you.

An autonomous AI software engineering agent inspired by The Matrix.
Works locally with **Ollama** or in the cloud with **BYOK** (Bring Your Own Key).

##  What it does

Neo is a terminal-based AI agent that:

- **Understands** your codebase before acting
- **Plans** changes step-by-step
- **Executes** with built-in tools (filesystem, terminal, git, web search)
- **Verifies** each change before moving on
- **Learns** from past tasks (persistent memory)

##  Quick Start

### Local (Ollama, 100% offline)

    ollama pull llama3.2
    python cli.py --provider ollama

### BYOK (OpenAI, Anthropic, DeepSeek)

    python cli.py --provider anthropic
    python cli.py --provider deepseek

##  Supported Providers

| Provider  | Type  | Setup                |
|-----------|-------|----------------------|
| Ollama    | Local | ollama pull llama3.2 |
| Anthropic | Cloud | ANTHROPIC_API_KEY    |
| OpenAI    | Cloud | OPENAI_API_KEY       |
| DeepSeek  | Cloud | DEEPSEEK_API_KEY     |

##  Architecture

    neo_code/
     cli.py          # Entry point
     config.py       # Configuration
     core/           # Agent engine
     providers/      # LLM backends
     tools/          # Built-in tools
     skills/         # Skill definitions
     ui/             # Terminal UI

##  Privacy

- **Ollama mode:** 100% offline. Nothing leaves your machine.
- **BYOK mode:** Direct connection to your provider. We store nothing.

##  License

Source Available  see LICENSE

---

**The protocol is the proof.** 
