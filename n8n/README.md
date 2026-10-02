# n8n workflows

Workflow exports live in `n8n/workflows/` (credentials excluded). The n8n UI is at
http://localhost:5678 once the stack is up. Workflows arrive in Phase 1 (task 1.5).

Environment values the workflows read (`$env.*`) are listed in `docker-compose.yml`.
`N8N_BLOCK_ENV_ACCESS_IN_NODE` is relaxed for dev only; use n8n credentials for staging/production.
