# Claude Cowork extension

This packages the `doc-qa-agent` MCP server as an Anthropic MCPB extension
(formerly DXT) so Claude Cowork picks up the three tools (`search_docs`,
`ask_docs`, `list_sources`) the same way it picks up the Apify connector.

## Files

- `manifest.json`: MCPB manifest. Declares the server type, the launch command,
  and the `python_path` user_config field that points the runtime at the
  project venv.
- `noop.py`: Empty file required by the MCPB validator (`server.entry_point`
  must resolve to a real file inside the bundle, even when the runtime
  command points at an external interpreter).
- `doc-qa-agent.mcpb`: The packed bundle. 1.2 kB. Re-pack with `mcpb pack .`
  after editing the manifest.

## Build

Once. Requires Node 18+ and npm.

```
npm install -g @anthropic-ai/mcpb
cd cowork-extension
mcpb validate manifest.json
mcpb pack . doc-qa-agent.mcpb
```

The `mcpb pack` output reports the SHA, file count, and size.

## Install in Claude Cowork (Windows)

Two paths.

Path A, double-click. File Explorer to `cowork-extension/`,
double-click `doc-qa-agent.mcpb`. Cowork is the registered handler for the
extension and opens the install dialog.

Path B, drag-drop. Open Cowork, navigate to Settings (or Customize) and
look for an Extensions panel. Drag `doc-qa-agent.mcpb` onto the panel.

In the install dialog Cowork shows the manifest fields and the user_config
prompt. The `python_path` field shows a placeholder default:

```
C:\path\to\doc-qa-agent\.venv\Scripts\python.exe
```

Click **Browse** and pick the real `python.exe` inside your cloned
`doc-qa-agent\.venv\Scripts\` directory, or paste the absolute path. Click
Install. Cowork extracts the bundle to:

```
%APPDATA%\Claude\Claude Extensions\<id>\
```

and adds an entry to `%APPDATA%\Claude\extensions-installations.json`.

Fully quit Cowork (right-click tray, Quit) and reopen. The doc-qa-agent
tools now show up alongside the rest of Cowork's MCP connectors.

## Verify

In a new Cowork chat:

```
Use the doc-qa-agent search_docs tool to find documentation about prompt
caching breakpoints.
```

Cowork invokes `search_docs`, prints the JSON response, and the model writes
a grounded answer.

If the tool does not appear after restart, check
`%APPDATA%\Claude\extensions-installations.json` for the doc-qa-agent entry,
then check `%APPDATA%\Claude\Claude Extensions\` for the extracted directory.
If both exist, the install succeeded and the issue is downstream of MCPB.

## Why the bundle does not ship the venv

The project has 100+ Python dependencies (anthropic, voyageai, psycopg,
pgvector, mcp, fastapi, etc) that would push the bundle past 500 MB. Instead
the manifest references the venv via `${user_config.python_path}`. The user
keeps a local checkout of the repo with `pip install -e .` already run.
That separation matches the pattern Anthropic recommends for development
extensions and keeps the bundle one minute to install.

For a production-shippable extension we would either:

1. Bundle a slim Python runtime via `python-build-standalone` plus a wheel
   directory (~80 MB), or
2. Have the install step run `pip install` against a packaged sdist.

Both are noted in `DAY_ONE.md` as iterations after the qualification project.
