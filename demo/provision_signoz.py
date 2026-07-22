from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = os.getenv("SIGNOZ_MCP_URL", "http://localhost:18000/mcp")
    output = {"dashboards": [], "alerts": [], "errors": []}
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            available = {tool.name for tool in (await session.list_tools()).tools}
            if "signoz_create_dashboard" not in available:
                raise RuntimeError("SigNoz MCP dashboard tools are unavailable")
            for path in sorted(Path("dashboards").glob("*.json")):
                definition = json.loads(path.read_text(encoding="utf-8"))
                try:
                    result = await session.call_tool("signoz_create_dashboard", definition)
                    output["dashboards"].append({"path": str(path), "result": str(result.content)})
                except Exception as exc:
                    output["errors"].append({"path": str(path), "error": str(exc)})
            alert_manifest = yaml.safe_load(Path("alerts/alerts.yaml").read_text(encoding="utf-8"))
            for alert in alert_manifest["alerts"]:
                try:
                    result = await session.call_tool("signoz_create_alert", alert)
                    output["alerts"].append({"name": alert["name"], "result": str(result.content)})
                except Exception as exc:
                    output["errors"].append({"name": alert["name"], "error": str(exc)})
    Path("data/demo-output").mkdir(parents=True, exist_ok=True)
    Path("data/demo-output/signoz-provisioning.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    if output["errors"]:
        raise SystemExit(
            "SigNoz provisioning completed with "
            f"{len(output['errors'])} errors; inspect "
            "data/demo-output/signoz-provisioning.json"
        )
    print(
        json.dumps(
            {"dashboards": len(output["dashboards"]), "alerts": len(output["alerts"])}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
