"""
api/function_app.py — Managed Function for Azure Static Web Apps.

Serves the data.js decryption password to browsers that Azure has already
authenticated via Entra ID (see staticwebapp.config.json's `auth` block and
the `allowedRoles: ["authenticated"]` route rule). Never reads the password
from source or git — only from the DATA_PASSWORD Application Setting,
configured out-of-band in the Azure Portal.

Without the Entra ID setup in place (Phase 2/3 of the rollout — see
HANDOVER.md), this endpoint has nothing to authenticate against and every
request 401s, which is intentional: build_dashboard.py's login flow falls
back to the manual password prompt when this returns anything but 200.
"""
import base64
import json
import os

import azure.functions as func

app = func.FunctionApp()


@app.function_name(name="get_data_key")
@app.route(route="get-data-key", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_data_key(req: func.HttpRequest) -> func.HttpResponse:
    principal_header = req.headers.get("x-ms-client-principal")
    if not principal_header:
        return func.HttpResponse(status_code=401)

    try:
        principal = json.loads(base64.b64decode(principal_header))
    except Exception:
        return func.HttpResponse(status_code=401)

    if "authenticated" not in (principal.get("userRoles") or []):
        return func.HttpResponse(status_code=401)

    password = os.environ.get("DATA_PASSWORD")
    if not password:
        return func.HttpResponse(status_code=500)

    return func.HttpResponse(
        json.dumps({"password": password}),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
