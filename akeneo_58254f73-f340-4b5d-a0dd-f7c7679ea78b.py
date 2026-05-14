import os
import sys
import json
import time
import traceback
from typing import Dict, Any, List, Optional

import requests
from flask import Flask, request, jsonify
from loguru import logger
import urllib.parse

# ---------------------------------------------------------------------
# Structured JSON logging configuration (for Cloud Run / GCP)
# ---------------------------------------------------------------------


def _json_log_sink(message: "loguru.Message") -> None:
    """
    Loguru sink that prints a single structured JSON per log record.

    Ensures Google Cloud Logging detects severity correctly by putting
    "severity" at the root level. Also includes:
      - message
      - function
      - line
      - time (RFC3339-ish)
    """
    record = message.record
    level = record["level"].name  # e.g., "INFO", "ERROR"
    dt = record["time"]
    log_dict = {
        "severity": level,
        "message": record["message"],
        "function": record["function"],
        "line": record["line"],
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    # merge extra fields if present
    if record.get("extra"):
        for key, value in record["extra"].items():
            # do not overwrite main fields
            if key not in log_dict:
                log_dict[key] = value
    sys.stdout.write(json.dumps(log_dict) + "\n")
    sys.stdout.flush()


# Configure loguru globally
logger.remove()
logger.add(_json_log_sink, level=os.getenv("LOG_LEVEL", "INFO"), backtrace=True, diagnose=False)

app = Flask(__name__)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
PLUMBED_BASE_URL = "http://localhost:5501"
ORGANIZATION_ID = "58254f73-f340-4b5d-a0dd-f7c7679ea78b"
CONNECTION_ID = (
    "akeneo_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b__"
    "shopify_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
)
SOURCE_OBJECT_NAME = "akeneo_58254f73-f340-4b5d-a0dd-f7c7679ea78b_products"
TRANSFORM_OBJECT_TYPE = "products"
CHANNEL_NAME = "akeneo_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
CHANNEL_TYPE = "source"

# ---------------------------------------------------------------------
# Helper functions (requested snippets, slightly adapted)
# ---------------------------------------------------------------------


def plumbed_bearer_token_verification(
    plumbed_base_url: str, bearer_token: str
) -> Dict[str, Any]:
    """
    Validate Plumbed bearer token via /user/get-user-info.

    Logs any 4xx/5xx errors with request and response payloads.
    """
    headers = {
        "Authorization": bearer_token,
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{plumbed_base_url}/user/get-user-info", headers=headers, timeout=30
        )
        if response.status_code in [200]:
            return response.json()
        logger.error(
            "Failed to authorize bearer_token with Plumbed",
            extra={
                "http_status": response.status_code,
                "request_headers": dict(response.request.headers or {}),
                "request_url": response.request.url,
                "request_method": response.request.method,
                "response_body": response.text,
            },
        )
        raise Exception(f"Failed to authorized bearer_token : {response.text}")
    except Exception as exc:
        logger.error(
            "Error while verifying Plumbed bearer token",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def get_connection_params(
    plumbed_base_url: str,
    bearer_token: str,
    channel_name: str,
    channel_type: str,
) -> Dict[str, Any]:
    """
    Get connection params for Akeneo source from Plumbed.

    Logs 4xx/5xx responses with full request/response information.
    """
    headers = {
        "Authorization": bearer_token,
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {
        "channel_name": channel_name,
        "channel_type": channel_type,
    }

    try:
        response = requests.get(
            f"{plumbed_base_url}/channel/get-single",
            headers=headers,
            params=params,
            timeout=30,
        )

        if response.status_code in [200]:
            result = response.json().get("result", [])
            if not result:
                raise Exception(
                    "No result found in Plumbed /channel/get-single response"
                )
            conn_params = result[0].get("connection_params")
            if not isinstance(conn_params, dict):
                raise Exception("connection_params missing or invalid in response")
            return conn_params

        logger.error(
            "Failed to get connection_params from Plumbed",
            extra={
                "http_status": response.status_code,
                "request_headers": dict(response.request.headers or {}),
                "request_url": response.request.url,
                "request_method": response.request.method,
                "request_params": params,
                "response_body": response.text,
            },
        )
        raise Exception(f"Failed to get the connection_params : {response.text}")
    except Exception as exc:
        logger.error(
            "Error while fetching connection params from Plumbed",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def transfer_data_to_plumbed(
    plumbed_base_url: str,
    bearer_token: str,
    organization_id: str,
    connection_id: str,
    source_object_name: str,
    transform_object_type: str,
    unique_id: str,
    propose_mapping: bool,
    product_data: List[Dict[str, Any]],
    sync_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Push data to Plumbed /transfer-source-json with URL encoding.

    - Uses bulk transfer endpoint (single API call per batch of items).
    - Can be called repeatedly for streaming scenarios.
    - Logs 4xx/5xx responses with full request/response info.
    """
    headers = {
        "Authorization": bearer_token,
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    logger.info(
        "Preparing to push products to Plumbed",
        extra={"products_count": len(product_data), "sync_mode": sync_mode},
    )

    encoded_data: List[Dict[str, Any]] = []
    for item in product_data:
        encoded_item = {
            key: (
                urllib.parse.quote_plus(value)
                if isinstance(value, str) and value.startswith("http")
                else value
            )
            for key, value in item.items()
        }
        encoded_data.append(encoded_item)

    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "connection_id": connection_id,
        "source_object_name": source_object_name,
        "transform_object_type": transform_object_type,
        "unique_id": unique_id,
        "propose_mapping": propose_mapping,
        "save_data_org_level": False,
        "data": encoded_data,
    }
    if sync_mode:
        payload["sync_mode"] = sync_mode

    try:
        response = requests.post(
            f"{plumbed_base_url}/transfer-source-json",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code in [200, 201]:
            logger.info(
                "Successfully pushed data to Plumbed",
                extra={
                    "http_status": response.status_code,
                    "products_count": len(product_data),
                },
            )
            return response.json()

        logger.error(
            "Failed to push data to Plumbed",
            extra={
                "http_status": response.status_code,
                "request_headers": dict(response.request.headers or {}),
                "request_url": response.request.url,
                "request_method": response.request.method,
                "request_body": payload,
                "response_body": response.text,
            },
        )
        raise Exception(f"Failed to push data to Plumbed: {response.text}")
    except Exception as exc:
        logger.error(
            "Error while pushing data to Plumbed",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


# ---------------------------------------------------------------------
# Akeneo helpers
# ---------------------------------------------------------------------


def generate_akeneo_access_token(conn_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a new Akeneo access_token using the documented OAuth2 flow.

    NOTE: Akeneo public API is OAuth2 (client_id + secret). In hosted Akeneo,
    they use an Akeneo-specific OAuth flow, but for OpenID Connect scenarios,
    the final result is still an OAuth2 access token used as Bearer.

    Expected connection params:
      - oidc_token_url: OpenID Connect token endpoint (if using OIDC explicitly)
      - client_id
      - client_secret
      - scope (optional)
      - username / password or authorization_code / refresh_token depending on flow
      - grant_type: "client_credentials" (recommended), "password", or "refresh_token"

    This function prefers standards-compliant OAuth2 as described in:
    https://api.akeneo.com/api-reference-index.html
    """
    client_id = conn_params.get("client_id")
    client_secret = conn_params.get("client_secret")
    grant_type = conn_params.get("grant_type", "client_credentials")
    oidc_token_url = conn_params.get("oidc_token_url")

    if not oidc_token_url:
        raise Exception("oidc_token_url missing in connection params for Akeneo OIDC")

    auth = (client_id, client_secret)
    data: Dict[str, Any] = {"grant_type": grant_type}

    # Common Akeneo/OpenID flows
    if grant_type == "client_credentials":
        scope = conn_params.get("scope")
        if scope:
            data["scope"] = scope
    elif grant_type == "password":
        username = conn_params.get("username")
        password = conn_params.get("password")
        if not username or not password:
            raise Exception("username/password required for password grant_type")
        data["username"] = username
        data["password"] = password
    elif grant_type == "refresh_token":
        refresh_token = conn_params.get("refresh_token")
        if not refresh_token:
            raise Exception("refresh_token grant_type but refresh_token missing")
        data["refresh_token"] = refresh_token
    else:
        raise Exception(f"Unsupported grant_type for Akeneo OIDC: {grant_type}")

    try:
        logger.info(
            "Requesting new Akeneo access token via OIDC endpoint",
            extra={"token_url": oidc_token_url, "grant_type": grant_type},
        )
        response = requests.post(oidc_token_url, data=data, auth=auth, timeout=30)

        if response.status_code in [200]:
            token_data = response.json()
            logger.info("Akeneo access token generated successfully")
            return token_data

        logger.error(
            "Failed to generate Akeneo access token",
            extra={
                "http_status": response.status_code,
                "request_url": response.request.url,
                "request_method": response.request.method,
                "request_body": data,
                "response_body": response.text,
            },
        )
        raise Exception(f"Failed to generate Akeneo access token: {response.text}")
    except Exception as exc:
        logger.error(
            "Error while generating Akeneo access token",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def get_akeneo_access_token(conn_params: Dict[str, Any]) -> str:
    """
    Obtain Akeneo access token:

    1. Prefer generating via OpenID Connect / OAuth2 flow (recommended by Akeneo).
    2. Fallback to static access_token in connection params, if present.
    """
    try:
        token_data = generate_akeneo_access_token(conn_params)
        access_token = token_data.get("access_token")
        if not access_token:
            raise Exception("No access_token in Akeneo token response")
        return access_token
    except Exception as exc:
        logger.warning(
            "Falling back to access_token from connection params due to error",
            extra={"exception": str(exc)},
        )

    existing_token = conn_params.get("access_token")
    if not existing_token:
        raise Exception(
            "Akeneo access_token not available; generation failed and no token in connection params"
        )
    logger.info("Using existing Akeneo access_token from connection params")
    return existing_token


def fetch_akeneo_products(
    akeneo_api_url: str,
    access_token: str,
    sync_mode: str,
    stream_to_plumbed: bool,
    plumbed_base_url: str,
    bearer_token: str,
    unique_id_key: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Fetch products from Akeneo with full pagination.

    - Uses Akeneo /api/rest/v1/products (latest public reference).
    - Implements pagination via 'next' link and search_after, as per docs.
    - When stream_to_plumbed is True, each page is pushed to Plumbed
      before fetching the next one (streaming mode).
    - For streaming, this function returns an empty list (since data is already sent).
      For non-streaming, returns the full list.

    sync_mode is forwarded to Plumbed but does not alter Akeneo endpoint,
    as Akeneo docs do not provide dedicated "delta" / "delete" endpoints
    in the provided context.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    products_endpoint = akeneo_api_url.rstrip("/") + "/api/rest/v1/products"
    params: Dict[str, Any] = {"limit": 100}

    all_products: List[Dict[str, Any]] = []
    next_url: Optional[str] = products_endpoint

    try:
        while next_url:
            logger.info(
                "Requesting Akeneo products page",
                extra={"url": next_url, "params": params},
            )
            response = requests.get(
                next_url, headers=headers, params=params if next_url == products_endpoint else None, timeout=60
            )

            if response.status_code != 200:
                logger.error(
                    "Akeneo products fetch failed",
                    extra={
                        "http_status": response.status_code,
                        "request_url": response.request.url,
                        "request_method": response.request.method,
                        "request_headers": dict(response.request.headers or {}),
                        "request_params": params if next_url == products_endpoint else None,
                        "response_body": response.text,
                    },
                )
                raise Exception(f"Failed to fetch Akeneo products: {response.text}")

            data = response.json()
            items = data.get("_embedded", {}).get("items", [])
            logger.info(
                "Fetched products from Akeneo page",
                extra={"page_count": len(items)},
            )

            if stream_to_plumbed:
                # streaming mode: push page immediately (use bulk API endpoint)
                if not unique_id_key and items:
                    unique_id_key = detect_unique_id_key(items)
                    logger.info(
                        "Detected unique_id key during streaming",
                        extra={"unique_id_key": unique_id_key},
                    )
                transfer_data_to_plumbed(
                    plumbed_base_url=plumbed_base_url,
                    bearer_token=bearer_token,
                    organization_id=ORGANIZATION_ID,
                    connection_id=CONNECTION_ID,
                    source_object_name=SOURCE_OBJECT_NAME,
                    transform_object_type=TRANSFORM_OBJECT_TYPE,
                    unique_id=unique_id_key or "uuid",
                    propose_mapping=True,
                    product_data=items,
                    sync_mode=sync_mode,
                )
            else:
                all_products.extend(items)

            links = data.get("_links", {})
            next_link = links.get("next", {})
            next_href = next_link.get("href")
            if next_href:
                next_url = next_href
                params = {}
            else:
                next_url = None

        if stream_to_plumbed:
            logger.info("Completed streaming Akeneo products to Plumbed")
            return []
        logger.info(
            "Total products fetched from Akeneo",
            extra={"total_count": len(all_products)},
        )
        return all_products
    except Exception as exc:
        logger.error(
            "Error while fetching Akeneo products",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def detect_unique_id_key(products: List[Dict[str, Any]]) -> str:
    """
    Determine the key representing the unique identifier for each product.

    Based on Akeneo sample, 'uuid' is the unique id.
    Fallback to 'identifier' or 'code' if 'uuid' is not present.
    """
    if not products:
        raise Exception("No products fetched from Akeneo to detect unique_id key")

    sample = products[0]
    if "uuid" in sample:
        return "uuid"
    if "identifier" in sample:
        return "identifier"
    if "code" in sample:
        return "code"

    raise Exception(
        "Unable to determine unique_id key from Akeneo product structure"
    )


# ---------------------------------------------------------------------
# Flask endpoint
# ---------------------------------------------------------------------


@app.route("/fetch_akeneo_products", methods=["POST"])
def fetch_akeneo_products_endpoint():
    """
    Trigger pull of products from Akeneo and push to Plumbed.

    - Protected via Bearer token (Plumbed) in Authorization header.
    - Accepts query parameter 'sync_mode' in ['full', 'delta', 'delete'], default 'full'.
    - When Plumbed connection_params include stream=true, each page of
      Akeneo data is directly streamed to Plumbed using bulk transfer,
      minimizing memory usage and maintaining upsert behavior.
    """
    sync_mode = request.args.get("sync_mode", "full").lower()
    if sync_mode not in ["full", "delta", "delete"]:
        logger.error(
            "Invalid sync_mode in request",
            extra={
                "sync_mode": sync_mode,
                "request_args": request.args.to_dict(),
            },
        )
        return (
            jsonify(
                {
                    "error": "Invalid sync_mode. Allowed values: full, delta, delete.",
                    "status": 400,
                }
            ),
            400,
        )

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        logger.error(
            "Missing Authorization header in request",
            extra={"request_headers": dict(request.headers)},
        )
        return (
            jsonify(
                {
                    "error": "Missing Authorization header",
                    "status": 401,
                }
            ),
            401,
        )

    bearer_token = auth_header

    try:
        # 1. Verify Plumbed bearer token
        logger.info("Verifying Plumbed bearer token...")
        plumbed_bearer_token_verification(PLUMBED_BASE_URL, bearer_token)

        # 2. Get Akeneo connection params from Plumbed
        logger.info("Fetching Akeneo connection params from Plumbed...")
        conn_params = get_connection_params(
            PLUMBED_BASE_URL,
            bearer_token,
            CHANNEL_NAME,
            CHANNEL_TYPE,
        )

        stream_flag = bool(conn_params.get("stream", False))

        # 3. Obtain Akeneo access_token via OpenID Connect / OAuth2
        logger.info("Obtaining Akeneo access token via OpenID Connect...")
        akeneo_access_token = get_akeneo_access_token(conn_params)

        # 4. Fetch products with pagination (and streaming if configured)
        akeneo_api_url = conn_params.get("akeneo_api_url")
        if not akeneo_api_url:
            raise Exception("akeneo_api_url missing in connection params")

        logger.info(
            "Fetching products from Akeneo",
            extra={"sync_mode": sync_mode, "stream": stream_flag},
        )

        unique_id_key: Optional[str] = None
        if not stream_flag:
            # For non-streaming we need unique_id ahead of final transfer
            # but we can also discover it after first page fetch.
            pass

        products = fetch_akeneo_products(
            akeneo_api_url=akeneo_api_url,
            access_token=akeneo_access_token,
            sync_mode=sync_mode,
            stream_to_plumbed=stream_flag,
            plumbed_base_url=PLUMBED_BASE_URL,
            bearer_token=bearer_token,
            unique_id_key=unique_id_key,
        )

        if stream_flag:
            # Data already streamed per page
            return (
                jsonify(
                    {
                        "message": "Akeneo products streamed to Plumbed successfully",
                        "streaming": True,
                        "sync_mode": sync_mode,
                        "status": 200,
                    }
                ),
                200,
            )

        if not products:
            logger.warning("No products fetched from Akeneo (non-streaming mode)")
            return jsonify({"message": "No products fetched from Akeneo", "status": 200})

        # 5. Detect unique_id key from Akeneo response
        unique_id_key = detect_unique_id_key(products)
        logger.info(
            "Detected unique_id key",
            extra={"unique_id_key": unique_id_key},
        )

        # 6. Push products to Plumbed using bulk transfer endpoint
        logger.info(
            "Pushing products to Plumbed transfer-source-json endpoint (non-streaming)",
            extra={"products_count": len(products), "sync_mode": sync_mode},
        )

        plumbed_response = transfer_data_to_plumbed(
            plumbed_base_url=PLUMBED_BASE_URL,
            bearer_token=bearer_token,
            organization_id=ORGANIZATION_ID,
            connection_id=CONNECTION_ID,
            source_object_name=SOURCE_OBJECT_NAME,
            transform_object_type=TRANSFORM_OBJECT_TYPE,
            unique_id=unique_id_key,
            propose_mapping=True,
            product_data=products,
            sync_mode=sync_mode,
        )

        logger.info(
            "Successfully completed Akeneo -> Plumbed sync",
            extra={"products_pushed": len(products), "sync_mode": sync_mode},
        )

        return (
            jsonify(
                {
                    "message": "Akeneo products synced to Plumbed successfully",
                    "products_count": len(products),
                    "unique_id": unique_id_key,
                    "sync_mode": sync_mode,
                    "plumbed_response": plumbed_response,
                    "status": 200,
                }
            ),
            200,
        )

    except Exception as exc:
        logger.error(
            "Error in /fetch_akeneo_products endpoint",
            extra={
                "exception": str(exc),
                "traceback": traceback.format_exc(),
                "request_headers": dict(request.headers),
                "request_args": request.args.to_dict(),
                "request_body": (request.get_json(silent=True) if request.is_json else None),
            },
        )
        return (
            jsonify(
                {
                    "error": str(exc),
                    "status": 500,
                }
            ),
            500,
        )


if __name__ == "__main__":
    # Flask debug=False; logs already configured for structured JSON
    app.run(host="0.0.0.0", port=8000, debug=False)