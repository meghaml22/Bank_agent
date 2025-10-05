

# 🧠 Bank Statement Parsing Agent

An autonomous AI agent that generates, tests, and self-corrects PDF parsers for any bank (ICICI, HDFC, SBI, Axis, etc.) using **Groq Llama 3**. It learns from a sample PDF and CSV, builds a parser automatically, and verifies the output without manual intervention.

Clone & Enter Folder
```bash
git clone https://github.com/yourusername/agent_bank.git
cd agent_bank
```
Create & Activate Virtual Environment

```bash
python -m venv venv
venv\Scripts\activate     # Windows
# or
source venv/bin/activate  # macOS/Linux
```

Install Requirements
```bash
pip install -r requirements.txt
```

Set Groq API Key/GEMINI_API_KEY
```bash
setx GROQ_API_KEY "your_api_key_here"
# or (macOS/Linux)
export GROQ_API_KEY="your_api_key_here"
```

Run the Agent
```bash
python agent.py --target icici
```

