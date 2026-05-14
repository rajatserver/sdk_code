import os
import sys
import json
import inspect
from typing import List, Dict, Any, Optional

from flask import Flask, request, jsonify
import requests
from loguru import logger

# ------------------------------------------------------------------------------
# Logging configuration (structured JSON for Cloud Logging)
# ------------------------------------------------------------------------------

def _json_log_sink(message):
    """
    Structured JSON logger sink for Loguru.

    Ensures that:
      - Each log entry is a single JSON object on one line.
      - Top-level fields: severity, message, function, line, time.
      - Extra context can be passed via logger.bind(...).
    """
    record = message.record
    log_obj = {
        "severity": record["level"].name,                 # e.g., INFO, WARNING, ERROR
        "message": record["message"],
        "function": record["function"],
        "line": record["line"],
        "time": record["time"].isoformat(),
    }
    # Merge in any contextual data passed via logger.bind(...)
    if record.get("extra"):
        log_obj.update(record["extra"])

    # Write to stdout as a single JSON line
    print(json.dumps(log_obj), file=sys.stdout)


# Configure loguru to use JSON sink
logger.remove()
logger.add(_json_log_sink, level="INFO", backtrace=False, diagnose=False)

# ------------------------------------------------------------------------------
# Basic setup
# ------------------------------------------------------------------------------

app = Flask(__name__)

PLUMBED_BASE_URL = "http://localhost:5501"

ORGANIZATION_ID = "58254f73-f340-4b5d-a0dd-f7c7679ea78b"
CONNECTION_ID = "akeneo_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b__shopify_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
TRANSFORM_OBJECT_TYPE = "products"
SOURCE_OBJECT_NAME = "akeneo_58254f73-f340-4b5d-a0dd-f7c7679ea78b_products"
TARGET_OBJECT_NAME = "shopify_58254f73-f340-4b5d-a0dd-f7c7679ea78b_products"

SHOPIFY_CHANNEL_NAME = "shopify_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
SHOPIFY_CHANNEL_TYPE = "target"

SHOPIFY_API_VERSION = "2026-01"  # future-compatible, per prompt; keep non-legacy

# ------------------------------------------------------------------------------
# Helper functions (Plumbed)
# ------------------------------------------------------------------------------

def plumbed_bearer_token_verification(plumbed_base_url: str, bearer_token: str) -> Dict[str, Any]:
    """
    Validate Plumbed bearer token using /user/get-user-info endpoint.

    Raises:
        Exception: if the call fails or returns non-200.
    """
    headers = {
        "Authorization": bearer_token,
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    url = f"{plumbed_base_url}/user/get-user-info"
    logger.info(
        "Verifying Plumbed bearer token",
        extra={"url": url}
    )
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.RequestException as exc:
        logger.error(
            "Error while verifying Plumbed bearer_token",
            extra={"url": url, "error": str(exc)}
        )
        raise Exception(f"Failed to authorize bearer_token due to connection error: {exc}") from exc

    if 199 <= response.status_code <= 299:
        logger.info(
            "Plumbed bearer token verification successful",
            extra={"url": url, "status_code": response.status_code}
        )
        return response.json()
    else:
        logger.error(
            "Failed to authorize bearer_token",
            extra={
                "url": url,
                "status_code": response.status_code,
                "response_body": response.text,
                "request_headers": headers,
            },
        )
        raise Exception(f"Failed to authorize bearer_token : {response.text}")


def transfer_data_from_plumbed(
    plumbed_base_url: str,
    bearer_token: str,
    organization_id: str,
    connection_id: str,
    transform_object_type: str,
    source_object_name: str,
    target_object_name: str,
    sync_mode: str,
    page: int = 1,
    limit: int = 20,
    filter_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch a single page of transformed products data from Plumbed using /transfer-target-json.

    Args:
        page: Page number to fetch.
        limit: Page size.
        filter_id: Optional Plumbed filter identifier.

    Returns:
        List of transformed product dictionaries.

    Raises:
        Exception: when unable to successfully fetch data.
    """
    headers = {
        "Authorization": bearer_token,
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "connection_id": connection_id,
        "transform_object_type": transform_object_type,
        "source_object_name": source_object_name,
        "target_object_name": target_object_name,
        "page": page,
        "limit": limit,
        "sync_mode": sync_mode,
    }

    if filter_id is not None:
        payload["filter_id"] = filter_id

    url = f"{plumbed_base_url}/transfer-target-json"
    logger.info(
        "Fetching products from Plumbed",
        extra={"url": url, "page": page, "limit": limit, "sync_mode": sync_mode, "payload": payload},
    )
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.exceptions.RequestException as exc:
        logger.error(
            "Error while calling Plumbed /transfer-target-json",
            extra={"url": url, "error": str(exc), "request_body": payload, "request_headers": headers},
        )
        raise Exception(f"Failed to pull data from Plumbed due to connection error: {exc}") from exc

    if 199 <= response.status_code <= 299:
        body = response.json()
        data = body.get("data", [])
        logger.info(
            "Fetched records from Plumbed",
            extra={
                "url": url,
                "status_code": response.status_code,
                "records_fetched": len(data),
                "page": page,
                "limit": limit,
            },
        )
        return data
    else:
        logger.error(
            "Failed to pull data from Plumbed",
            extra={
                "url": url,
                "status_code": response.status_code,
                "response_body": response.text,
                "request_body": payload,
                "request_headers": headers,
            },
        )
        raise Exception(f"Failed to pull data from Plumbed: {response.text}")


def get_connection_params(
    plumbed_base_url: str,
    bearer_token: str,
    channel_name: str,
    channel_type: str,
) -> Dict[str, Any]:
    """
    Get connection parameters for Shopify from Plumbed /channel/get-single.

    Returns:
        connection_params dict.

    Raises:
        Exception: if the call fails or response structure is invalid.
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

    url = f"{plumbed_base_url}/channel/get-single"
    logger.info(
        "Fetching connection params from Plumbed",
        extra={"url": url, "params": params},
    )
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.exceptions.RequestException as exc:
        logger.error(
            "Error while calling Plumbed /channel/get-single",
            extra={"url": url, "error": str(exc), "request_headers": headers, "request_params": params},
        )
        raise Exception(f"Failed to get the connection_params due to connection error: {exc}") from exc

    if 199 <= response.status_code <= 299:
        try:
            body = response.json()
            result = body.get("result", [])
            if not result:
                raise Exception("Empty result array in connection params response")
            connection_params = result[0].get("connection_params", {}) or {}
            logger.info(
                "Successfully fetched connection params from Plumbed",
                extra={"url": url, "has_access_token": bool(connection_params.get("access_token"))},
            )
            return connection_params
        except Exception as exc:
            logger.error(
                "Error parsing connection params",
                extra={
                    "url": url,
                    "status_code": response.status_code,
                    "response_body": response.text,
                    "error": str(exc),
                },
            )
            raise
    else:
        logger.error(
            "Failed to get the connection_params",
            extra={
                "url": url,
                "status_code": response.status_code,
                "response_body": response.text,
                "request_headers": headers,
                "request_params": params,
            },
        )
        raise Exception(f"Failed to get the connection_params : {response.text}")


# ------------------------------------------------------------------------------
# Helper functions (Shopify)
# ------------------------------------------------------------------------------

def build_shopify_base_url(connection_params: Dict[str, Any]) -> str:
    """
    Determine Shopify base URL from connection params.

    Priority:
      1. connection_params['api_url'] if present (e.g. https://your-store.myshopify.com/admin/api)
      2. Construct from connection_params['shop_name'].

    Returns:
        Base URL without trailing slash and without version suffix.
    """
    api_url = connection_params.get("api_url")
    shop_name = connection_params.get("shop_name")

    if api_url:
        base_url = api_url.rstrip("/")
    elif shop_name:
        base_url = f"https://{shop_name}.myshopify.com/admin/api"
    else:
        raise Exception("Neither 'api_url' nor 'shop_name' is available in connection params")

    return base_url


def generate_shopify_access_token(connection_params: Dict[str, Any]) -> str:
    """
    Return Shopify access token.

    Uses documented header:
        X-Shopify-Access-Token: {access_token}

    Raises:
        Exception: if access_token is missing.
    """
    access_token = connection_params.get("access_token")
    if not access_token:
        raise Exception(
            "Shopify access_token is not present in connection_params "
            "and automatic OAuth token generation is not implemented."
        )
    return access_token


def push_products_to_shopify(
    connection_params: Dict[str, Any],
    products: List[Dict[str, Any]],
    sync_mode: str,
) -> Dict[str, Any]:
    """
    Push (create/update/delete) products to Shopify using single-product REST API.

    As per the provided Shopify docs:
      - Authentication uses X-Shopify-Access-Token header.
      - Single product endpoints are used; we iterate products with a for-loop.

    Since no official bulk or upsert endpoint is documented in the provided context,
    this implementation uses per-product operations only, with proper logging.

    All responses with HTTP status codes 199–299 are treated as success.

    Args:
        connection_params: Dict containing Shopify credentials and endpoint info.
        products: List of Plumbed-transformed Shopify product payloads.
        sync_mode: "full", "delta", or "delete".

    Returns:
        Dict: summary of operations performed.
    """
    results: Dict[str, Any] = {"pushed": 0, "deleted": 0, "errors": []}

    base_url_root = build_shopify_base_url(connection_params)
    base_url = f"{base_url_root}/{SHOPIFY_API_VERSION}"
    access_token = generate_shopify_access_token(connection_params)

    headers = {
        "X-Shopify-Access-Token": access_token,  # per Shopify doc
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(
        "Using Shopify base URL",
        extra={"base_url": base_url_root, "versioned_base_url": base_url},
    )

    for index, product in enumerate(products):
        product_id = product.get("id")
        try:
            # For create/update we send body; for delete we only use the id.
            if sync_mode == "delete":
                # DELETE /admin/api/{version}/products/{product_id}.json
                if not product_id:
                    error_message = "Product 'id' is required for delete sync_mode but not found in product data"
                    logger.error(
                        "Missing product id for delete operation",
                        extra={"index": index, "product": product, "error": error_message},
                    )
                    results["errors"].append({"index": index, "error": error_message})
                    continue

                url = f"{base_url}/products/{product_id}.json"
                logger.info(
                    "Deleting Shopify product",
                    extra={"index": index, "product_id": product_id, "url": url},
                )
                try:
                    response = requests.delete(url, headers=headers, timeout=60)
                except requests.exceptions.RequestException as exc:
                    logger.error(
                        "Connection error while deleting product on Shopify",
                        extra={
                            "index": index,
                            "product_id": product_id,
                            "url": url,
                            "error": str(exc),
                            "request_headers": headers,
                        },
                    )
                    results["errors"].append(
                        {"index": index, "product_id": product_id, "error": f"Connection error: {exc}"}
                    )
                    continue

                if 199 <= response.status_code <= 299:
                    results["deleted"] += 1
                else:
                    logger.error(
                        "Failed to delete product on Shopify",
                        extra={
                            "index": index,
                            "product_id": product_id,
                            "url": url,
                            "status_code": response.status_code,
                            "response_body": response.text,
                            "request_headers": headers,
                        },
                    )
                    results["errors"].append(
                        {
                            "index": index,
                            "product_id": product_id,
                            "status_code": response.status_code,
                            "body": response.text,
                            "operation": "delete",
                        }
                    )
            else:
                # full / delta -> create or update (single-product API, per docs)
                if product_id:
                    url = f"{base_url}/products/{product_id}.json"
                    method = "PUT"
                else:
                    url = f"{base_url}/products.json"
                    method = "POST"

                shopify_payload = {"product": product}
                logger.info(
                    "Pushing product to Shopify",
                    extra={
                        "index": index,
                        "method": method,
                        "url": url,
                        "product_id": product_id,
                    },
                )

                try:
                    if method == "POST":
                        response = requests.post(url, headers=headers, json=shopify_payload, timeout=60)
                    else:
                        response = requests.put(url, headers=headers, json=shopify_payload, timeout=60)
                except requests.exceptions.RequestException as exc:
                    logger.error(
                        "Connection error while pushing product to Shopify",
                        extra={
                            "index": index,
                            "product_id": product_id,
                            "url": url,
                            "method": method,
                            "error": str(exc),
                            "request_headers": headers,
                            "request_body": shopify_payload,
                        },
                    )
                    results["errors"].append(
                        {"index": index, "product_id": product_id, "error": f"Connection error: {exc}"}
                    )
                    continue

                if 199 <= response.status_code <= 299:
                    results["pushed"] += 1
                else:
                    # 400 / 500 etc: log error with headers + body + request body
                    logger.error(
                        "Failed to push product to Shopify",
                        extra={
                            "index": index,
                            "product_id": product_id,
                            "url": url,
                            "method": method,
                            "status_code": response.status_code,
                            "response_body": response.text,
                            "request_headers": headers,
                            "request_body": shopify_payload,
                        },
                    )
                    results["errors"].append(
                        {
                            "index": index,
                            "product_id": product_id,
                            "status_code": response.status_code,
                            "body": response.text,
                            "operation": method,
                        }
                    )

        except Exception as exc:
            logger.error(
                "Unexpected error while processing product",
                extra={"index": index, "product_id": product_id, "error": str(exc)},
            )
            results["errors"].append({"index": index, "error": str(exc)})

    return results


# ------------------------------------------------------------------------------
# Flask endpoint
# ------------------------------------------------------------------------------

@app.route("/store_shopify_products", methods=["POST"])
def store_shopify_products():
    """
    Main endpoint to:
      1. Validate Plumbed bearer token.
      2. Determine sync_mode.
      3. Fetch Shopify connection params.
      4. Page through Plumbed data (always implements pagination).
      5. Push products to Shopify, using per-product REST endpoints.
      6. Optionally support streaming mode (stream=true in connection_params),
         where each page is pushed immediately prior to fetching the next one.

    Returns:
        JSON summary of the synchronization.
    """
    # ------------------------------------------------------------------
    # 1. Get and validate bearer token from headers with Plumbed
    # ------------------------------------------------------------------
    bearer_token = request.headers.get("Authorization")
    if not bearer_token:
        logger.warning(
            "Missing Authorization header",
            extra={"endpoint": "/store_shopify_products"},
        )
        return jsonify({"error": "Missing Authorization header"}), 401

    try:
        plumbed_bearer_token_verification(PLUMBED_BASE_URL, bearer_token)
    except Exception as exc:
        logger.error(
            "Authorization with Plumbed failed",
            extra={"endpoint": "/store_shopify_products", "error": str(exc)},
        )
        return jsonify({"error": "Unauthorized", "details": str(exc)}), 401

    # ------------------------------------------------------------------
    # 2. Read query param sync_mode (default: full)
    # ------------------------------------------------------------------
    sync_mode = request.args.get("sync_mode", "full").lower()
    if sync_mode not in ("full", "delta", "delete"):
        logger.warning(
            "Invalid sync_mode received",
            extra={"endpoint": "/store_shopify_products", "sync_mode": sync_mode},
        )
        return jsonify({"error": "Invalid sync_mode. Allowed: full, delta, delete"}), 400

    # ------------------------------------------------------------------
    # 3. Optional filter_id from JSON body
    # ------------------------------------------------------------------
    filter_id = None
    if request.data:
        try:
            body_json = request.get_json(force=True, silent=True) or {}
            filter_id = body_json.get("filter_id")
        except Exception as exc:
            logger.error(
                "Failed to parse JSON body",
                extra={
                    "endpoint": "/store_shopify_products",
                    "error": str(exc),
                    "raw_body": request.data.decode("utf-8", errors="ignore"),
                },
            )
            return jsonify({"error": "Invalid JSON body", "details": str(exc)}), 400

    # ------------------------------------------------------------------
    # 4. Get Shopify connection params from Plumbed
    # ------------------------------------------------------------------
    try:
        connection_params = get_connection_params(
            PLUMBED_BASE_URL,
            bearer_token,
            channel_name=SHOPIFY_CHANNEL_NAME,
            channel_type=SHOPIFY_CHANNEL_TYPE,
        )
    except Exception as exc:
        logger.error(
            "Failed to get Shopify connection params",
            extra={"endpoint": "/store_shopify_products", "error": str(exc)},
        )
        return jsonify({"error": "Failed to get connection params", "details": str(exc)}), 500

    stream_mode = bool(connection_params.get("stream", False))

    # ------------------------------------------------------------------
    # 5. Fetch all pages of products from Plumbed and push to Shopify
    #    Always implement pagination. Page size can be tuned.
    # ------------------------------------------------------------------
    page = 1
    limit = 50  # larger but still reasonable for per-product REST operations
    total_received = 0
    aggregated_result = {"pushed": 0, "deleted": 0, "errors": []}

    while True:
        try:
            products = transfer_data_from_plumbed(
                PLUMBED_BASE_URL,
                bearer_token,
                ORGANIZATION_ID,
                CONNECTION_ID,
                TRANSFORM_OBJECT_TYPE,
                SOURCE_OBJECT_NAME,
                TARGET_OBJECT_NAME,
                sync_mode=sync_mode,
                page=page,
                limit=limit,
                filter_id=filter_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to fetch products from Plumbed",
                extra={
                    "endpoint": "/store_shopify_products",
                    "page": page,
                    "limit": limit,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Failed to fetch products from Plumbed", "details": str(exc)}), 500

        if not products:
            if page == 1:
                logger.info(
                    "No products returned from Plumbed for given parameters",
                    extra={
                        "endpoint": "/store_shopify_products",
                        "sync_mode": sync_mode,
                        "page": page,
                        "limit": limit,
                    },
                )
            break

        total_received += len(products)

        # ------------------------------------------------------------------
        # 6. Push data to Shopify page by page (for-loop per single-product API)
        # ------------------------------------------------------------------
        try:
            page_result = push_products_to_shopify(connection_params, products, sync_mode)
        except Exception as exc:
            logger.error(
                "Failed while communicating with Shopify",
                extra={
                    "endpoint": "/store_shopify_products",
                    "page": page,
                    "limit": limit,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Failed while communicating with Shopify", "details": str(exc)}), 500

        # Aggregate page results
        aggregated_result["pushed"] += page_result.get("pushed", 0)
        aggregated_result["deleted"] += page_result.get("deleted", 0)
        aggregated_result["errors"].extend(page_result.get("errors", []))

        # If streaming mode is enabled, we conceptually "save" after each page.
        # Plumbed-specific save endpoint is not provided; this is a placeholder
        # to indicate where such a call would occur.
        if stream_mode:
            logger.info(
                "Streaming mode enabled: processed page",
                extra={
                    "endpoint": "/store_shopify_products",
                    "page": page,
                    "limit": limit,
                    "products_processed": len(products),
                    "stream": True,
                },
            )
            # If there were a Plumbed "save page" API, it would be called here.

        page += 1

    response_body = {
        "sync_mode": sync_mode,
        "page_size": limit,
        "total_products_received": total_received,
        "shopify_result": aggregated_result,
    }

    logger.info(
        "Completed /store_shopify_products synchronization",
        extra={
            "endpoint": "/store_shopify_products",
            "sync_mode": sync_mode,
            "total_products_received": total_received,
            "pushed": aggregated_result["pushed"],
            "deleted": aggregated_result["deleted"],
            "error_count": len(aggregated_result["errors"]),
        },
    )

    return jsonify(response_body), 200


# ------------------------------------------------------------------------------
# Run (for local testing)
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    # You can adjust host/port as needed.
    app.run(host="0.0.0.0", port=8000, debug=False)