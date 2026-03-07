# Agent Installer

A one-click Windows installer for the LangGraph AI agent.

## For Users

Double-click `AgentInstaller.exe` to launch the installer wizard. It will:

1. Check your system for required software (Python, Node.js, Git, Docker)
2. Install any missing dependencies automatically
3. Set up your database (Railway cloud or local PostgreSQL)
4. Optionally set up Hindsight episodic memory (requires Docker, **30+ minutes first run**)
5. Collect your API keys and configure the agent
6. Install all Python and npm packages
7. Launch the agent

> **Note about Docker/Hindsight:** The first time Docker downloads the Hindsight image, it can take 30+ minutes depending on your internet speed. The installer shows a live progress bar so you can see it's working. Your agent is NOT broken — it just takes a while!

## For Developers: Building the EXE

### Prerequisites

```powershell
# Create a separate venv for the installer build tools
python -m venv installer\.venv-build
installer\.venv-build\Scripts\activate
pip install -r installer\requirements.txt
```

### Build

```powershell
cd installer
python build.py
```

The EXE will be at `installer/dist/AgentInstaller.exe`.

Copy it to the project root before distributing:

```powershell
copy installer\dist\AgentInstaller.exe AgentInstaller.exe
```

### Adding a custom icon

Place a 256x256 `.ico` file at `installer/assets/icon.ico` before building.
You can convert a PNG to ICO at https://convertio.co/png-ico/

## Running the installer without building

If you have Python 3.11+ installed, you can run the installer directly:

```powershell
pip install customtkinter psycopg[binary]
python installer/main.py
```
