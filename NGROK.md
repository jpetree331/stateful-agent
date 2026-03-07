# Public Dashboard via ngrok

Expose your the agent dashboard publicly with one ngrok tunnel. Everything runs locally; ngrok creates a public URL.

## Password protection (recommended)

Add to your `.env`:
```
DASHBOARD_PASSWORD=your-secret-password
```

When set, visitors get a browser login popup. Username can be anything; password must match. Leave unset for no auth (local dev only).

## Quick start

1. **Build the dashboard** (one-time, or after changes):
   ```bash
   cd dashboard && npm run build
   ```

2. **Start the API** (serves dashboard + API on port 8000):
   ```bash
   python -m src.agent.api
   ```

3. **In another terminal, start ngrok**:
   ```bash
   ngrok http 8000
   ```

4. Open the ngrok URL (e.g. `https://your-subdomain.ngrok-free.app in your browser.

## One-command option

```bash
python scripts/start_public_dashboard.py
```

This builds the dashboard and starts the API. Then run `ngrok http 8000` in a second terminal.

## After dashboard updates

1. `cd dashboard && npm run build`
2. Restart the API (Ctrl+C, then `python -m src.agent.api`)
3. ngrok keeps running — no changes needed

## Telegram webhook (no polling)

When using ngrok, set in `.env`:
```
TELEGRAM_WEBHOOK_URL=https://your-subdomain.ngrok-free.app
```

Telegram will push updates to your server instead of long-polling. Zero API calls when idle.

## Notes

- Your PC must stay on for the dashboard to be reachable.
- The API and dashboard are served from the same origin, so no CORS setup is needed.
- If you use ngrok's custom domain (Hobby plan), the URL stays the same across restarts.
