# Agent Dashboard

Chat UI for the agent. For local testing:

1. **Start the API** (in one terminal):
   ```bash
   python -m src.agent.api
   ```

2. **Start the dashboard** (in another terminal):
   ```bash
   cd dashboard; npm run dev
   ```
   (PowerShell: use `;` not `&&`. Or: `cd dashboard` then `npm run dev`.)

3. Open http://localhost:5173 and chat.

The dashboard proxies `/api` requests to the backend at `localhost:8000`.
