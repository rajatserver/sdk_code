# This is 58254f73-f340-4b5d-a0dd-f7c7679ea78b org shopify sdk

from flask import Flask, request, jsonify
import requests
from loguru import logger
import sys
import time
import os
import json
import re

app = Flask(__name__)

# JSON logs
logger.remove()
logger.add(sys.stdout, serialize=True, format="{time} {level} {message}")

# ---- Plumbed config ----
PLUMBED_BASE_URL = "http://localhost:5501"
ORGANIZATION_ID = "58254f73-f340-4b5d-a0dd-f7c7679ea78b"
CONNECTION_ID = "akeneo_test_58254f73-f340-4b5d-a0dd-f7c7679ea78b__shopify_test_github_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
TRANSFORM_OBJECT_TYPE = "products"
SOURCE_OBJECT_NAME = "akeneo_58254f73-f340-4b5d-a0dd-f7c7679ea78b_products"
TARGET_OBJECT_NAME = "shopify_58254f73-f340-4b5d-a0dd-f7c7679ea78b_products"
CHANNEL_NAME = "shopify_test_github_58254f73-f340-4b5d-a0dd-f7c7679ea78b"
CHANNEL_TYPE = "target"

# ---- Tunables ----
RATE_LIMIT_SLEEP = float(os.getenv("RATE_LIMIT_SLEEP", "0"))  # optional delay between productCreate calls
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))              # only used for logging chunks
BULK_THRESHOLD = int(os.getenv("SHOPIFY_BULK_THRESHOLD", "300"))

# ---- Shopify ProductInput whitelists ----
PRODUCT_INPUT_KEYS = {
    "title","descriptionHtml","handle","tags","vendor","productType","status",
    "templateSuffix","giftCard","seo","variants","media",
    "collectionsToJoin","collectionsToLeave","metafields","productOptions",
}
PRODUCT_OPTION_KEYS = {"name","position","values"}
PRODUCT_SEO_KEYS = {"title","description"}

# For OptionCreateInput (used in productOptions)
PRODUCT_OPTION_KEYS = {"name", "position", "values"}  # values = list of { "name": "Blue" }

# For ProductVariantsBulkInput (create/update via bulk mutations)
PRODUCT_VARIANT_KEYS = {
    "id",                 # for updates only
    "barcode",
    "compareAtPrice",
    "inventoryItem",      # e.g., {"sku": "ABC-123"}  (see InventoryItemInput)
    "inventoryPolicy",
    "inventoryQuantities",# only valid on bulk CREATE
    "mediaId",
    "mediaSrc",
    "metafields",
    "optionValues",       # list of { optionName: "Color", name: "Blue" }
    "price",
    "requiresComponents",
    "showUnitPrice",
    "taxable",
    "taxCode",
    "unitPriceMeasurement",
    # (No: title/options/weight/weightUnit/position/sku)
}

# Keys considered "known" (won't go into plumbed.raw)
KNOWN_TOP_LEVEL_KEYS = set(PRODUCT_INPUT_KEYS) | {"id", "name", "product_type", "variants"}

# Exclude legacy option fields & other known variant fields from per-field metafields
VARIANT_KNOWN_KEYS = set(PRODUCT_VARIANT_KEYS) | {"option1","option2","option3","options","name"}

# at top-level (near helpers)
MAX_SHOPIFY_TEXT = 65535  # Shopify text limits

def _clean_text_for_metafield(s: str, single_line: bool) -> str:
    # normalize newlines + strip control chars except tab
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if single_line:
        s = s.replace("\n", " ").strip()
    # hard cap to Shopify limit to avoid rejections
    if len(s) > MAX_SHOPIFY_TEXT:
        s = s[:MAX_SHOPIFY_TEXT]
    return s

def _infer_metafield_type(val):
    # Keep it small & safe; Shopify expects string-typed values for most custom types unless you use typed definitions.
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "number_integer" if isinstance(val, int) else "number_decimal"
    if isinstance(val, (dict, list)):
        return "json"
    return "single_line_text_field"

def _stringify_metafield_value(val):
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)

def _extras_to_typed_metafields(obj: dict, known_keys: set, namespace="plumbed") -> list:
    """
    Convert unknown keys of `obj` into Shopify metafields with correct type.
    """
    import json

    metafields = []
    extra_fields = {k: obj[k] for k in obj.keys() - known_keys if obj.get(k) is not None}

    for key, val in extra_fields.items():
        if isinstance(val, bool):
            mf_type, mf_value = "boolean", str(val).lower()
        elif isinstance(val, int):
            mf_type, mf_value = "number_integer", str(val)
        elif isinstance(val, float):
            mf_type, mf_value = "number_decimal", str(val)
        elif isinstance(val, str):
            # pick single-line vs multi-line based on presence of newlines
            if ("\n" in val) or ("\r" in val):
                mf_type = "multi_line_text_field"
                mf_value = _clean_text_for_metafield(val, single_line=False)
            else:
                mf_type = "single_line_text_field"
                mf_value = _clean_text_for_metafield(val, single_line=True)
        
        else:
            mf_type, mf_value = "json", json.dumps(val, ensure_ascii=False, separators=(",", ":"))

        metafields.append({
            "namespace": namespace,
            "key": key,
            "type": mf_type,
            "value": mf_value,
        })
    return metafields

def _copy_keys(source_dict: dict, allowed_keys: set) -> dict:
    return {key: source_dict[key] for key in (allowed_keys & source_dict.keys())}

def _slugify_title_to_handle(s: str) -> str:
    """
    Generate a Shopify-friendly handle from a title ONLY when no handle is provided.
    Leaves existing handles untouched elsewhere.
    """
    if not s:
        return ""
    out = s.lower()
    out = re.sub(r"[^a-z0-9]+", "-", out)   # collapse non-alphanumerics to dashes
    out = re.sub(r"-{2,}", "-", out)        # collapse runs, but this is only for generated handles
    return out.strip("-")

def _extras_to_metafield(product: dict) -> list:
    """Pack arbitrary extra fields into a single JSON metafield: plumbed.raw"""
    extra_fields = {key: value for key, value in product.items() if key not in KNOWN_TOP_LEVEL_KEYS}
    if not extra_fields:
        return []
    return [{
        "namespace": "plumbed",
        "key": "raw",
        "type": "json",
        "value": json.dumps(extra_fields, ensure_ascii=False, separators=(",", ":"))
    }]

def map_product_to_productinput(source_product: dict) -> dict:
    """
    Build a valid Shopify ProductInput from arbitrary product dict `source_product`.
    - Coerces types/values into what GraphQL expects
    - Drops/omits illegal/empty fields
    - Preserves unknowns into metafields: plumbed.raw
    """
    product_input = _copy_keys(source_product, PRODUCT_INPUT_KEYS)
    
    # NEW: coerce stringified JSON to a list
    po = product_input.get("productOptions")
    if isinstance(po, str):
        try:
            product_input["productOptions"] = json.loads(po)
        except Exception:
            pass
    # Extract values for size and color
    size_values = source_product.get("values_size", {}).get("data", [])
    color_values = source_product.get("values_color", {}).get("data", [])

    # ---- Fallback: support nested productOptions.values_size / values_color (your sample) ----
    if (not size_values and not color_values) and isinstance(source_product.get("productOptions"), dict):
        po = source_product["productOptions"]
        if isinstance(po.get("values_size"), dict):
            size_values = po["values_size"].get("data", []) or po["values_size"].get(0) or po["values_size"]
        if isinstance(po.get("values_color"), dict):
            color_values = po["values_color"].get("data", []) or po["values_color"].get(0) or po["values_color"]

    # --- STRICT: only advertise options if BOTH axes exist ---
    color_list = [str(v).strip() for v in (color_values or []) if str(v).strip()]
    size_list  = [str(v).strip() for v in (size_values  or []) if str(v).strip()]

    if color_list and size_list:
        product_input["productOptions"] = [
            {"name": "Color", "values": color_list},
            {"name": "Size",  "values": size_list},
        ]
    else:
        # drop any pre-supplied productOptions; prevents single-axis products
        product_input.pop("productOptions", None)

    # Title (non-empty fallback)
    title_text = (source_product.get("title") or source_product.get("name") or "").strip()
    product_input["title"] = title_text if title_text else f"Product-{source_product.get('id', '')}"

    # Optional mapping from source "product_type" -> GraphQL "productType"
    if "product_type" in source_product and "productType" not in product_input and source_product["product_type"] is not None:
        product_input["productType"] = str(source_product["product_type"])

    # Handle: keep if present; otherwise derive from title
    if str(product_input.get("handle") or "").strip():
        # keep as-is (DO NOT slugify provided handles)
        pass
    else:
        # no handle provided: synthesize from title so new products have a stable handle
        synthesized = _slugify_title_to_handle(product_input.get("title"))
        if synthesized:
            product_input["handle"] = synthesized
        else:
            product_input.pop("handle", None)

    # Tags -> list[str]
    if "tags" in product_input:
        tags_value = product_input["tags"]
        if isinstance(tags_value, str):
            tags_value = [tag.strip() for tag in tags_value.split(",") if tag.strip()]
        elif isinstance(tags_value, list):
            tags_value = [str(tag).strip() for tag in tags_value if str(tag).strip()]
        else:
            tags_value = []
        if tags_value:
            product_input["tags"] = tags_value
        else:
            product_input.pop("tags", None)

    # Status enum
    if "status" in product_input:
        status_value = product_input["status"]
        if isinstance(status_value, bool):
            product_input["status"] = "ACTIVE" if status_value else "DRAFT"
        elif isinstance(status_value, str):
            normalized_status = status_value.strip().upper()
            if normalized_status in {"ACTIVE", "DRAFT", "ARCHIVED"}:
                product_input["status"] = normalized_status
            else:
                product_input.pop("status", None)
        else:
            product_input.pop("status", None)

    # Variants (drop empty objects)
    if isinstance(source_product.get("variants"), list):
        mapped_variants = []
        for variant in source_product["variants"]:
            if not isinstance(variant, dict):
                continue
            mapped_variant = {key: variant[key] for key in (PRODUCT_VARIANT_KEYS & variant.keys())}
            if "options" in mapped_variant and isinstance(mapped_variant["options"], list):
                mapped_variant["options"] = [str(option_value) for option_value in mapped_variant["options"]]
            # retain only if it has SOME data
            if any(mapped_variant.get(key) not in (None, "", [], {}) for key in mapped_variant.keys()):
                mapped_variants.append(mapped_variant)
        if mapped_variants:
            product_input["variants"] = mapped_variants
        else:
            product_input.pop("variants", None)

    # SEO
    if isinstance(source_product.get("seo"), dict):
        seo_input = {}
        seo_title = source_product["seo"].get("title")
        seo_description = source_product["seo"].get("description")
        if isinstance(seo_title, str) and seo_title.strip():
            seo_input["title"] = seo_title
        if isinstance(seo_description, str) and seo_description.strip():
            seo_input["description"] = seo_description
        if seo_input:
            product_input["seo"] = seo_input
        else:
            product_input.pop("seo", None)

    # Append plumbed.raw metafield
    metafield_extras = _extras_to_metafield(source_product)
    if metafield_extras:
        if isinstance(product_input.get("metafields"), list):
            product_input["metafields"] = product_input["metafields"] + metafield_extras
        else:
            product_input["metafields"] = metafield_extras

    return product_input

def _normalize_product_options_for_create(obj: dict):
    po = obj.get("productOptions")
    if not isinstance(po, list):
        obj.pop("productOptions", None)
        return

    cleaned = []
    for o in po:
        if not isinstance(o, dict):
            continue
        name = str(o.get("name") or "").strip()
        if not name:
            continue

        vals = o.get("values")
        if isinstance(vals, list) and vals:
            # Shopify wants list of objects: [{"name": "Blue"}], not ["Blue"]
            vals_objs = [{"name": str(v).strip()} for v in vals if str(v).strip()]
            if vals_objs:
                cleaned.append({"name": name, "values": vals_objs})
            else:
                cleaned.append({"name": name})
        else:
            cleaned.append({"name": name})

    if cleaned:
        obj["productOptions"] = cleaned
    else:
        obj.pop("productOptions", None)

def _batched_variant_ids_by_sku_for_handles(graphql_url, headers, handles: list[str]) -> dict[str, dict[str, str]]:
    """
    Return {handle: {sku: variantId}} for given handles.
    """
    out: dict[str, dict[str, str]] = {}
    if not handles:
        return out

    CHUNK = 30
    q_tmpl = """
    query($q: String!) {
      products(first: 250, query: $q) {
        edges {
          node {
            handle
            variants(first: 250) {
              edges { node { id sku } }
            }
          }
        }
      }
    }
    """
    for i in range(0, len(handles), CHUNK):
        chunk = [h for h in handles[i:i+CHUNK] if h]
        if not chunk:
            continue
        term = " OR ".join([f"handle:{h}" for h in chunk])
        j = _graphqlexec(graphql_url, headers, q_tmpl, {"q": term})
        edges = ((((j.get("data") or {}).get("products") or {}).get("edges") or []))
        for e in edges:
            n = e.get("node") or {}
            h = n.get("handle")
            if not h:
                continue
            vmap = {}
            for ve in ((((n.get("variants") or {}).get("edges") or []))):
                vn = ve.get("node") or {}
                sku = (vn.get("sku") or "").strip()
                vid = vn.get("id")
                if sku and vid:
                    vmap[sku] = vid
            out[h] = vmap
    return out

def _money_or_none(val):
    if val is None:
        return None
    s = str(val).strip().replace(",", ".")
    if not s:
        return None
    try:
        return f"{float(s):.2f}"
    except Exception:
        return None

def _build_variant_payloads(source_product: dict, mapped_product_input: dict) -> list[dict]:
    """
    Convert source variants into ProductVariantsBulkInput.
    - Reads option names from productOptions (NOT legacy 'options')
    - Prefers explicit variant.optionValues (ensuring optionName)
    - Falls back to variant.options list, then option1/2/3, then single-option fallback
    - Sanitizes money; does NOT send unsupported 'title'
    """
    # Read option names from productOptions
    option_names = []
    if isinstance(mapped_product_input.get("productOptions"), list):
        option_names = [
            str(o.get("name", "")).strip()
            for o in mapped_product_input["productOptions"]
            if isinstance(o, dict) and o.get("name")
        ]
    if not option_names:
        # If there is no explicit option on the product, Shopify uses implicit "Title"
        option_names = ["Title"]

    out = []
    for v in (source_product.get("variants") or []):
        if not isinstance(v, dict):
            continue

        item = {}

        # Money fields
        p = _money_or_none(v.get("price"))
        if p is not None:
            item["price"] = p
        cap = _money_or_none(v.get("compareAtPrice"))
        if cap is not None:
            item["compareAtPrice"] = cap

        # Safe copies (omit unsupported 'title')
        for k in ["barcode","taxable","requiresShipping","weight","weightUnit","inventoryPolicy","position"]:
            val = v.get(k)
            if val not in (None, "", [], {}):
                item[k] = val
        # Map SKU into inventoryItem (GraphQL bulk expects SKU here)
        sku_raw = v.get("sku")
        if isinstance(sku_raw, str):
            sku_raw = sku_raw.strip()
        if sku_raw:
            inv = item.get("inventoryItem") or {}
            inv["sku"] = sku_raw
            item["inventoryItem"] = inv
        # Normalize weight unit to Shopify enums (plural)
        wu = item.get("weightUnit")
        if isinstance(wu, str):
            repl = {"GRAM":"GRAMS","KILOGRAM":"KILOGRAMS","OUNCE":"OUNCES","POUND":"POUNDS"}
            if wu in repl:
                item["weightUnit"] = repl[wu]

        # Build optionValues
        ovs = []
        
        # ---- NEW: helper inline to coerce/normalize one pair ----
        def _append_normalized(i_idx, raw_name, raw_option_name):
            name_val = str(raw_name or "").strip()
            # If optionName is missing or not one of declared names, map by index fallback
            opt_name = str(raw_option_name or "").strip()
            if not opt_name or opt_name not in option_names:
                if 0 <= i_idx < len(option_names):
                    opt_name = option_names[i_idx]
                elif option_names:
                    opt_name = option_names[0]
            if name_val and opt_name:
                ovs.append({"name": name_val, "optionName": opt_name})


        # 1) Prefer explicit variant.optionValues
        ov_in = v.get("optionValues")

        if isinstance(ov_in, list) and ov_in:
            # list of dicts
            for i, ov in enumerate(ov_in):
                if not isinstance(ov, dict):
                    continue
                _append_normalized(i, ov.get("name"), ov.get("optionName"))

        elif isinstance(ov_in, dict) and ov_in:
            # ---- NEW: support dict-of-arrays shape: {"name":[...], "optionName":[...]}
            names_arr = ov_in.get("name") or ov_in.get("names") or []
            onames_arr = ov_in.get("optionName") or ov_in.get("optionNames") or []
            # If "optionName" entries are NOT one of declared option names, treat them as the SECOND axis *values*
            looks_like_values = bool(onames_arr) and all(
                str(x or "").strip() not in option_names for x in onames_arr
            )
            if looks_like_values and len(option_names) >= 2:
                max_len = max(len(names_arr), len(onames_arr))
                for i in range(max_len):
                    cval = names_arr[i] if i < len(names_arr) else None   # e.g., "green"
                    sval = onames_arr[i] if i < len(onames_arr) else None  # e.g., "l"
                    # pair color -> option_names[0], size -> option_names[1]
                    _append_normalized(0, cval, option_names[0])
                    _append_normalized(1, sval, option_names[1])
            else:
                max_len = max(len(names_arr), len(onames_arr)) if (names_arr or onames_arr) else 0
                for i in range(max_len):
                    nval = names_arr[i] if i < len(names_arr) else None
                    onval = onames_arr[i] if i < len(onames_arr) else None
                    _append_normalized(i, nval, onval)


        # 2) Fallback: positional list v.options -> optionValues
        elif isinstance(v.get("options"), list) and v["options"]:
            for i, val in enumerate(v["options"]):
                if i < len(option_names) and val not in (None, ""):
                    _append_normalized(i, val, option_names[i])

        # 3) Fallback: legacy option1/2/3
        else:
            legacy_vals = [v.get("option1"), v.get("option2"), v.get("option3")]
            if any(x not in (None, "") for x in legacy_vals):
                for i, val in enumerate(legacy_vals):
                    if i < len(option_names) and val not in (None, ""):
                        _append_normalized(i, val, option_names[i])
        
            elif len(option_names) == 1:
                # 4) Last resort for single option
                fallback = v.get("name") or source_product.get("title") or "Default Title"
                _append_normalized(0, fallback, option_names[0])

        
        # ---- Minimal guard: require complete axis coverage for multi-axis products ----
        # Clean out empties so the count is meaningful
        ovs = [
            ov for ov in ovs
            if isinstance(ov, dict)
            and str(ov.get("optionName", "")).strip()
            and str(ov.get("name", "")).strip()
        ]
        if len(option_names) > 1 and len(ovs) != len(option_names):
            continue

        if ovs:
            item["optionValues"] = ovs

        # --- NEW: attach extra variant fields as typed metafields ---
        vmfs = _extras_to_typed_metafields(v, VARIANT_KNOWN_KEYS, namespace="plumbed")
        if vmfs:
            if isinstance(item.get("metafields"), list):
                item["metafields"] = item["metafields"] + vmfs
            else:
                item["metafields"] = vmfs

        out.append(item)

    return out
def _ensure_product_options(graphql_url, headers, product_id: str, option_names: list[str]):
    if not option_names:
        return
    q = """
    query ($id: ID!) {
      product(id: $id) { options(first: 3) { name position } }
    }"""
    res = _graphqlexec(graphql_url, headers, q, {"id": product_id})
    existing = [ (o.get("name") or "").strip() for o in (((res.get("data") or {})
                     .get("product") or {}).get("options") or []) if o ]
    want = [n for n in option_names if n]

    # If any desired option is missing, create options
    if any(n not in existing for n in want):
        mut = """
        mutation ($id: ID!, $options: [OptionCreateInput!]!) {
          productOptionsCreate(productId: $id, options: $options) {
            userErrors { field message }
          }
        }"""
        # supply only names and positions; values come from variants
        options = [{"name": n, "position": i+1} for i, n in enumerate(want)]
        jr = _graphqlexec(graphql_url, headers, mut, {"id": product_id, "options": options})
        errs = ((((jr.get("data") or {}).get("productOptionsCreate") or {}).get("userErrors")) or [])
        if errs:
            logger.error({"severity":"ERROR","message":"productOptionsCreate_errors","product_id":product_id,"errors":errs})

def _apply_variants_for_products(
    graphql_url,
    headers,
    source_by_handle: dict[str, dict],
    mapped_by_handle: dict[str, dict],
    handle_to_product_id: dict[str, str],
):
    handles = [
        h for h in handle_to_product_id.keys()
        if h in source_by_handle and source_by_handle[h].get("variants")
    ]
    if not handles:
        return

    by_handle_sku_to_id = _batched_variant_ids_by_sku_for_handles(graphql_url, headers, handles)

    mut_update = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!, $allowPartial: Boolean) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants, allowPartialUpdates: $allowPartial) {
        userErrors { field message }
      }
    }"""
    mut_create = """
    mutation(
      $productId: ID!,
      $variants: [ProductVariantsBulkInput!]!,
      $strategy: ProductVariantsBulkCreateStrategy!
    ) {
      productVariantsBulkCreate(
        productId: $productId,
        variants: $variants,
        strategy: $strategy
      ) {
        userErrors { field message }
      }
    }

    """

    for h in handles:
        pid = handle_to_product_id.get(h)
        src = source_by_handle.get(h) or {}
        mp  = mapped_by_handle.get(h) or {}
        if not pid:
            continue

        # --- ADDED: only create variants when BOTH Color and Size are declared on the product ---
        opt_names = [
            (o.get("name") or "").strip().lower()
            for o in (mp.get("productOptions") or [])
            if isinstance(o, dict)
        ]
        if not ("color" in opt_names and "size" in opt_names):
            logger.info({
                "severity": "INFO",
                "message": "skip_variants_missing_axes",
                "handle": h,
                "option_names": opt_names
            })
            continue
        # --- END ADDED ---
        bulk_inputs = _build_variant_payloads(src, mp)
        if not bulk_inputs:
            continue

        sku_to_id = by_handle_sku_to_id.get(h, {})
        to_update, to_create = [], []
        for vi in bulk_inputs:
            inv = vi.get("inventoryItem") or {}
            sku = (vi.get("sku") or inv.get("sku") or "").strip()
            if sku and sku in sku_to_id:
                vi_upd = dict(vi) 
                vi_upd["id"] = sku_to_id[sku]
                vi_upd.pop("sku", None) 
                to_update.append(vi_upd)
            else:
                vi_cr = dict(vi)
                vi_cr.pop("sku", None)
                to_create.append(vi_cr)

        if to_update:
            jr = _graphqlexec(graphql_url, headers, mut_update,
                              {"productId": pid, "variants": to_update, "allowPartial": True})
            errs = ((((jr.get("data") or {}).get("productVariantsBulkUpdate") or {}).get("userErrors")) or [])
            if errs:
                logger.error({
                    "severity": "ERROR",
                    "message": "variants_bulk_update_errors",
                    "handle": h,
                    "option_order": [ (o.get("name") or "").strip() for o in ((mp.get("productOptions") or [])) if isinstance(o, dict) ],
                    "attempted_variants": [
                        {
                            "sku": ((vi.get("inventoryItem") or {}).get("sku") or vi.get("sku") or "").strip(),
                            "options": [
                                f"{(ov.get('optionName') or '').strip()}={(ov.get('name') or '').strip()}"
                                for ov in (vi.get("optionValues") or []) if isinstance(ov, dict)
                            ]
                        }
                        for vi in to_update
                    ],
                    "errors": errs
                })


        if to_create:
            jr = _graphqlexec(graphql_url, headers, mut_create,
                              {"productId": pid, "variants": to_create, "strategy": "REMOVE_STANDALONE_VARIANT"})
            errs = ((((jr.get("data") or {}).get("productVariantsBulkCreate") or {}).get("userErrors")) or [])
            if errs:
                logger.error({
                    "severity": "ERROR",
                    "message": "variants_bulk_create_errors",
                    "handle": h,
                    "option_order": [ (o.get("name") or "").strip() for o in ((mp.get("productOptions") or [])) if isinstance(o, dict) ],
                    "attempted_variants": [
                        {
                            "sku": ((vi.get("inventoryItem") or {}).get("sku") or vi.get("sku") or "").strip(),
                            "options": [
                                f"{(ov.get('optionName') or '').strip()}={(ov.get('name') or '').strip()}"
                                for ov in (vi.get("optionValues") or []) if isinstance(ov, dict)
                            ]
                        }
                        for vi in to_create
                    ],
                    "errors": errs
                })


def _get_shop_id(graphql_url, headers) -> str:
    q = "query { shop { id } }"
    j = _graphqlexec(graphql_url, headers, q)
    sid = (((j.get("data") or {}).get("shop") or {}).get("id"))
    if not sid:
        raise Exception("Could not resolve shop id")
    return sid

def ensure_metadata_definition_exists_once(graphql_url, headers):
    """
    Ensure the plumbed.raw metafield definition exists ONCE per shop.
    We mark success by setting a Shop metafield: namespace=plumbed, key=setup_done, value=true.
    """

    # Resolve Shop GID (needed to set a shop metafield)
    shop_id = _get_shop_id(graphql_url, headers)

    # 1) Check 'setup_done' flag on the shop
    query_flag = """
    query ($ns: String!, $key: String!) {
      shop {
        metafield(namespace: $ns, key: $key) { value }
      }
    }
    """
    flag_res = _graphqlexec(
        graphql_url, headers, query_flag,
        {"ns": "plumbed", "key": "setup_done"}
    )
    flag_val = ((((flag_res.get("data") or {}).get("shop") or {}).get("metafield") or {}) or {}).get("value")
    if str(flag_val).lower() == "true":
        logger.info({"severity": "INFO", "message": "setup_done=true — skipping metafield definition", "function": "ensure_metadata_definition_exists_once"})
        return

    # 2) Ensure the product-level metafield definition exists
    query_def = """
    query {
      metafieldDefinitions(ownerType: PRODUCT, first: 1, namespace: "plumbed") {
        edges { node { id } }
      }
    }
    """
    def_res = _graphqlexec(graphql_url, headers, query_def)
    exists = bool(def_res.get("data", {}).get("metafieldDefinitions", {}).get("edges"))
    if not exists:
        mutation_def = """
        mutation CreateDef($def: MetafieldDefinitionInput!) {
          metafieldDefinitionCreate(definition: $def) {
            createdDefinition { id namespace key ownerType }
            userErrors { field message }
          }
        }
        """
        def_vars = {
            "def": {
                "name": "Plumbed Raw",
                "namespace": "plumbed",
                "key": "raw",
                "ownerType": "PRODUCT",
                "type": "json",
            }
        }
        mres = _graphqlexec(graphql_url, headers, mutation_def, def_vars)
        merrs = (((mres.get("data") or {}).get("metafieldDefinitionCreate") or {}).get("userErrors")) or []
        if merrs:
            raise Exception(f"MetafieldDefinitionCreate errors: {merrs}")

    # 3) Set the shop-level flag so future runs skip everything
    mutation_flag = """
    mutation SetSetupFlag($id: ID!) {
      metafieldsSet(metafields: [
        { namespace: "plumbed", key: "setup_done", type: "boolean", value: "true", ownerId: $id }
      ]) {
        userErrors { field message }
      }
    }
    """
    fres = _graphqlexec(graphql_url, headers, mutation_flag, {"id": shop_id})
    # (Optional) you can inspect fres['data']['metafieldsSet']['userErrors'] if desired

    logger.info({"severity": "INFO", "message": "Metafield def ensured; setup_done=true set", "function": "ensure_metadata_definition_exists_once"})

# ---------- Plumbed helpers ----------
def plumbed_bearer_token_verification(bearer_token):
    headers = {"Authorization": bearer_token, "accept": "application/json", "Content-Type": "application/json"}
    response = requests.get(f"{PLUMBED_BASE_URL}/user/get-user-info", headers=headers)
    if response.status_code == 200:
        return response.json()
    logger.error({
        "severity": "ERROR",
        "message": f"Failed to authorize bearer_token: {response.text}",
        "function": "plumbed_bearer_token_verification",
        "time": time.time()
    })
    raise Exception(f"Failed to authorize bearer_token: {response.text}")

def transfer_data_from_plumbed(bearer_token, sync_mode):
    headers = {"Authorization": bearer_token, "accept": "application/json", "Content-Type": "application/json"}
    current_page = 1
    page_limit = 100
    all_products = []
    while True:
        payload = {
            "organization_id": ORGANIZATION_ID,
            "connection_id": CONNECTION_ID,
            "transform_object_type": TRANSFORM_OBJECT_TYPE,
            "source_object_name": SOURCE_OBJECT_NAME,
            "target_object_name": TARGET_OBJECT_NAME,
            "page": current_page,
            "limit": page_limit,
            "sync_mode": sync_mode
        }
        response = requests.post(f"{PLUMBED_BASE_URL}/transfer-target-json", headers=headers, json=payload)
        if 200 <= response.status_code < 300:
            page_data = response.json().get("data", [])
            if not page_data:
                break
            all_products.extend(page_data)
            current_page += 1
        else:
            logger.error({
                "severity": "ERROR",
                "message": f"Failed to fetch data from Plumbed: {response.text}",
                "function": "transfer_data_from_plumbed",
                "time": time.time()
            })
            raise Exception(f"Failed to fetch data from Plumbed: {response.text}")
    return all_products

def get_connection_params(bearer_token):
    headers = {"Authorization": bearer_token, "accept": "application/json", "Content-Type": "application/json"}
    query_params = {"channel_name": CHANNEL_NAME, "channel_type": CHANNEL_TYPE}
    response = requests.get(f"{PLUMBED_BASE_URL}/channel/get-single", headers=headers, params=query_params)
    if response.status_code == 200:
        return response.json().get("result")[0].get("connection_params")
    logger.error({
        "severity": "ERROR",
        "message": f"Failed to get the connection_params: {response.text}",
        "function": "get_connection_params",
        "time": time.time()
    })
    raise Exception(f"Failed to get the connection_params: {response.text}")

def _cancel_current_bulk_if_running(graphql_url, headers):
    cur_q = """query { currentBulkOperation { id status } }"""
    r = requests.post(graphql_url, headers=headers, json={"query": cur_q})
    r.raise_for_status()
    cur = (r.json().get("data") or {}).get("currentBulkOperation") or {}
    if cur.get("status") in ("CREATED", "RUNNING"):
        cancel_mut = """mutation { bulkOperationCancel { bulkOperation { id status } userErrors { field message } } }"""
        rc = requests.post(graphql_url, headers=headers, json={"query": cancel_mut})
        rc.raise_for_status()

def _poll_bulk_operation_by_id(graphql_url, headers, op_id, max_wait_sec=1800):
    query = """
    query ($id: ID!) {
      node(id: $id) {
        ... on BulkOperation {
          id status errorCode objectCount createdAt completedAt url
        }
      }
    }
    """
    waited, sleep_sec = 0, 2
    while True:
        r = requests.post(graphql_url, headers=headers, json={"query": query, "variables": {"id": op_id}})
        r.raise_for_status()
        node = ((r.json().get("data") or {}).get("node") or {})
        status = node.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELED"):
            return node
        time.sleep(sleep_sec)
        waited += sleep_sec
        sleep_sec = min(int(sleep_sec * 1.5) or 1, 20)
        if waited >= max_wait_sec:
            raise TimeoutError("Timed out waiting for bulk operation to finish")

def _graphqlexec(graphql_url, headers, query, variables=None):
    r = requests.post(graphql_url, headers=headers, json={"query": query, "variables": variables or {}})
    r.raise_for_status()
    j = r.json()
    if "errors" in j and j["errors"]:
        raise Exception(f"GraphQL errors: {j['errors']}")
    return j

def _get_product_id_by_handle(graphql_url, headers, handle: str):
    if not handle:
        return None
    q = """
    query ($q: String!) {
      products(first: 1, query: $q) {
        edges { node { id handle } }
      }
    }
    """
    res = _graphqlexec(graphql_url, headers, q, {"q": f"handle:{handle}"})
    edges = (((res.get("data") or {}).get("products") or {}).get("edges") or [])
    if not edges:
        return None
    node = edges[0].get("node") or {}
    return node.get("id") if node.get("handle") == handle else None

def _get_existing_ids_by_handle(graphql_url, headers, handles: list[str]) -> dict:
    """
    Return {handle: product_id} for the subset of handles that already exist.
    Queries in small batches using Shopify's product search (handle:foo OR handle:bar).
    """
    out = {}
    CHUNK = 30  # keep queries small/safe
    q_tmpl = """
    query ($q: String!) {
      products(first: 250, query: $q) {
        edges { node { id handle } }
      }
    }
    """
    for i in range(0, len(handles), CHUNK):
        chunk = [h for h in handles[i:i+CHUNK] if h]
        if not chunk:
            continue
        # Build 'handle:h1 OR handle:h2 ...'
        term = " OR ".join([f"handle:{h}" for h in chunk])
        res = _graphqlexec(graphql_url, headers, q_tmpl, {"q": term})
        edges = (((res.get("data") or {}).get("products") or {}).get("edges") or [])
        for e in edges:
            node = e.get("node") or {}
            h = node.get("handle")
            pid = node.get("id")
            if h and pid:
                out[h] = pid
    return out

def _summarize_and_log_bulk_result(result_url: str, head_lines: int = 50):
    """
    Downloads Shopify bulk result JSONL and logs:
      - created / updated / failed counts
      - up to `head_lines` raw lines for quick inspection
      - sample error messages (up to 3)
    """
    try:
        resp = requests.get(result_url, timeout=120)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        logger.error({
            "severity": "ERROR",
            "message": f"Failed to download bulk result: {e}",
            "result_url": result_url,
            "function": "_summarize_and_log_bulk_result",
            "time": time.time()
        })
        return

    created = updated = failed = 0
    samples = []
    for ln, line in enumerate(text.splitlines(), start=1):
        # stop heavy parsing after ~50k lines to protect logs (adjust if you like)
        if ln > 50000:
            break
        try:
            obj = json.loads(line)
        except Exception:
            failed += 1
            if len(samples) < 3:
                samples.append(f"L{ln}: invalid JSON line")
            continue

        pu = (((obj.get("data") or {}).get("productUpdate") or {}))
        pc = (((obj.get("data") or {}).get("productCreate") or {}))
        if pu:
            errs = pu.get("userErrors") or []
            if errs:
                failed += 1
                if len(samples) < 3:
                    samples.append(f"Update L{ln}: " + ", ".join(e.get("message", "") for e in errs))
            else:
                updated += 1
        elif pc:
            errs = pc.get("userErrors") or []
            if errs:
                failed += 1
                if len(samples) < 3:
                    samples.append(f"Create L{ln}: " + ", ".join(e.get("message", "") for e in errs))
            else:
                created += 1
        else:
            errs = obj.get("errors") or []
            if errs:
                failed += 1
                if len(samples) < 3:
                    samples.append(f"L{ln} top-level: {errs}")

    # Log summary
    logger.info({
        "severity": "INFO",
        "message": "bulk_result_summary",
        "created": created,
        "updated": updated,
        "failed": failed,
        "error_samples": samples,
        "total_lines": len(text.splitlines()),
        "function": "_summarize_and_log_bulk_result",
        "time": time.time()
    })

    # Also log a small head of raw lines for quick eyeballing (optional)
    if head_lines > 0:
        head = "\n".join(text.splitlines()[:head_lines])
        logger.info({
            "severity": "INFO",
            "message": "bulk_result_head",
            "head_lines": head_lines,
            "raw_head": head,
            "function": "_summarize_and_log_bulk_result",
            "time": time.time()
        })

# New function to handle bulk product creation
def bulk_product_create(products, connection_params):
    graphql_url = connection_params["graphql_url"]
    access_token = connection_params["x_shopify_access_token"]
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": access_token}

    # Ensure a clean slate (Shopify allows only one bulk op at a time)
    _cancel_current_bulk_if_running(graphql_url, headers)

    # --- Map inputs & gather handles (dedupe by last occurrence to avoid within-batch collisions)
    from collections import defaultdict
    source_by_handle = defaultdict(lambda: {"variants": []})
    latest_by_handle = {}  # handle -> mapped input
    mapped_inputs = []
    mapped_by_handle = {}
    for p in products:
        m = map_product_to_productinput(p)
        # keep using your existing KNOWN_TOP_LEVEL_KEYS
        pmfs = _extras_to_typed_metafields(p, KNOWN_TOP_LEVEL_KEYS, namespace="plumbed")

        if pmfs:
            if isinstance(m.get("metafields"), list):
                m["metafields"] = m["metafields"] + pmfs
            else:
                m["metafields"] = pmfs

        # canonical handle = parent (for bundling), else its own handle
        canon = (p.get("parent") or m.get("handle") or "").strip()
        if not canon:
            # no handle at all → skip creating variants for this row
            # (optional: still allow the product to be created if you want)
            continue
        canon = str(canon)

        # ✅ normalize to Shopify-style handle (lowercase; spaces → hyphens)
        canon_norm = canon.lower().replace(" ", "-")
        
        # ensure the skeleton uses the canonical handle
        m["handle"] = canon_norm

        # keep one product skeleton per canonical handle (last wins is fine)
        latest_by_handle[canon_norm] = m
        mapped_by_handle[canon_norm] = m
        handle_key = canon_norm

        # 🔴 WHY here: we append variants while we’re already iterating the rows,
        # so siblings don’t overwrite each other later.
        if p.get("parent") is None:
            # keep the product skeleton, but do NOT aggregate variants from this row
            continue_variant_collect = False
        else:
            continue_variant_collect = True

        if continue_variant_collect:
            vlist = p.get("variants") or []
            if isinstance(vlist, list) and vlist:
                source_by_handle[canon]["variants"].extend(vlist)

    # one product per canonical handle
    deduped = list(latest_by_handle.values())

    # --- Pre-fetch existing IDs for non-empty handles
    handles = [ (x.get("handle") or "").strip() for x in deduped if (x.get("handle") or "").strip() ]
    existing = _get_existing_ids_by_handle(graphql_url, headers, handles) if handles else {}

    # --- Split lines into UPDATE (with id) and CREATE
    update_lines, create_lines = [], []
    for m in deduped:
        h = (m.get("handle") or "").strip()
        if h:
            h = str(h).lower().replace(" ", "-")   # ✅ normalize here
            m["handle"] = h                        # ensure the payload uses normalized handle
        else:
            m.pop("handle", None)
        pid = existing.get(h)
        if pid:
            m_upd = dict(m)
            m_upd["id"] = pid
            # ---- strip variants for product bulk ----
            m_upd_no_variants = dict(m_upd)
            m_upd_no_variants.pop("variants", None)
            m_upd_no_variants.pop("optionValues", None)
            m_upd_no_variants.pop("productOptions", None)
            # --- NEW: add extra fields as typed metafields (product-level) ---
            pmfs = _extras_to_typed_metafields(m_upd_no_variants, KNOWN_TOP_LEVEL_KEYS, namespace="plumbed")
            if pmfs:
                if isinstance(m_upd_no_variants.get("metafields"), list):
                    m_upd_no_variants["metafields"] = m_upd_no_variants["metafields"] + pmfs
                else:
                    m_upd_no_variants["metafields"] = pmfs
 
            _normalize_product_options_for_create(m_upd_no_variants)
            update_lines.append(json.dumps({"input": m_upd_no_variants}, ensure_ascii=False, separators=(",", ":")))
        else:
            # ---- strip variants for product bulk ----
            m_no_variants = dict(m)
            m_no_variants.pop("variants", None)
            m_no_variants.pop("optionValues", None)
            # --- NEW: add extra fields as typed metafields (product-level) ---
            pmfs = _extras_to_typed_metafields(m_no_variants, KNOWN_TOP_LEVEL_KEYS, namespace="plumbed")
            if pmfs:
                if isinstance(m_no_variants.get("metafields"), list):
                    m_no_variants["metafields"] = m_no_variants["metafields"] + pmfs
                else:
                    m_no_variants["metafields"] = pmfs

            _normalize_product_options_for_create(m_no_variants)
            create_lines.append(json.dumps({"input": m_no_variants}, ensure_ascii=False, separators=(",", ":")))

    mutation_update = """
    mutation bulkUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id handle }
        userErrors { field message }
      }
    }
    """
    mutation_create = """
    mutation bulkCreate($input: ProductInput!) {
      productCreate(input: $input) {
        product { id handle }
        userErrors { field message }
      }
    }
    """

    def _stage_and_run(jsonl_data: str, mutation_string: str):
        # 1) stagedUploadsCreate
        staged_upload_mutation = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }
        """
        staged_vars = {"input": [{
            "resource": "BULK_MUTATION_VARIABLES",
            "filename": "products.jsonl",
            "mimeType": "text/jsonl",
            "httpMethod": "POST"
        }]}
        r = requests.post(graphql_url, headers=headers, json={"query": staged_upload_mutation, "variables": staged_vars})
        r.raise_for_status()
        sr = r.json()
        errs = (((sr.get("data") or {}).get("stagedUploadsCreate") or {}).get("userErrors")) or []
        if errs:
            raise Exception(f"stagedUploadsCreate errors: {errs}")
        target = (sr["data"]["stagedUploadsCreate"]["stagedTargets"] or [])[0]
        upload_url = target["url"]
        params = {p["name"]: p["value"] for p in target["parameters"]}

        # 2) S3 POST (accept 200/201/204; parse <Key> fallback)
        files = {"file": ("products.jsonl", jsonl_data, "text/jsonl")}
        upload_resp = requests.post(upload_url, data=params, files=files)
        if upload_resp.status_code not in (200, 201, 204):
            raise Exception(f"Bulk JSONL upload failed: HTTP {upload_resp.status_code} {upload_resp.text[:300]}")
        staged_key = params.get("key")
        if not staged_key:
            try:
                import re
                m = re.search(r"<Key>(.*?)</Key>", upload_resp.text)
                if m:
                    staged_key = m.group(1)
            except Exception:
                pass
        if not staged_key:
            raise Exception(f"Could not determine staged upload key; response was: {upload_resp.text[:300]}")

        # 3) Run bulkOperationRunMutation
        run_bulk_mutation = """
        mutation bulkOperationRunMutation($mutation: String!, $stagedUploadPath: String!) {
          bulkOperationRunMutation(mutation: $mutation, stagedUploadPath: $stagedUploadPath) {
            bulkOperation { id status }
            userErrors { field message }
          }
        }
        """
        r2 = requests.post(
            graphql_url, headers=headers,
            json={"query": run_bulk_mutation, "variables": {"mutation": mutation_string, "stagedUploadPath": staged_key}}
        )
        r2.raise_for_status()
        br = r2.json()
        run_errors = (((br.get("data") or {}).get("bulkOperationRunMutation") or {}).get("userErrors")) or []
        if run_errors:
            raise Exception(f"bulkOperationRunMutation errors: {run_errors}")
        op_id = br["data"]["bulkOperationRunMutation"]["bulkOperation"]["id"]

        node = _poll_bulk_operation_by_id(graphql_url, headers, op_id, max_wait_sec=1800)
        logger.info({
            "severity": "INFO",
            "message": "bulk_status",
            "status": node.get("status"),
            "objectCount": node.get("objectCount"),
            "errorCode": node.get("errorCode"),
            "result_url": node.get("url"),
            "function": "bulk_product_create/_stage_and_run",
            "time": time.time()
        })
        if node.get("status") != "COMPLETED":
            raise Exception(f"Bulk op ended with status={node.get('status')}, errorCode={node.get('errorCode')}")
        # NEW: download + log the result text & summary (no more manual checking)
        result_url = node.get("url")
        if result_url:
            _summarize_and_log_bulk_result(result_url, head_lines=50)  # tweak head_lines as you like
    # --- Run updates first (if any), then creates (if any)
    if update_lines:
        _stage_and_run("\n".join(update_lines), mutation_update)
    if create_lines:
        _stage_and_run("\n".join(create_lines), mutation_create)

    # After you've aggregated variants into source_by_handle keyed by canonical handle
    handles_for_variants = [h for h in source_by_handle.keys() if h]
    
    if handles_for_variants:
        handle_to_id_final = _get_existing_ids_by_handle(
            graphql_url, headers, handles_for_variants
        )
        
        for h in handles_for_variants:
            pid = handle_to_id_final.get(h)
            if not pid:
                continue
            mp = mapped_by_handle.get(h) or {}
            names = [ (o.get("name") or "").strip()
                  for o in (mp.get("productOptions") or []) if isinstance(o, dict) ]
            _ensure_product_options(graphql_url, headers, pid, names)
        # Only proceed if at least one non-null parent product ID exists
        if any(handle_to_id_final.values()):
            _apply_variants_for_products(
                graphql_url,
                headers,
                source_by_handle,     # read variants from the source
                mapped_by_handle,     
                handle_to_id_final    # product id per handle
            )

    return {
        "ok": True,
        "updated_count": len(update_lines),
        "created_count": len(create_lines)
    }

def _upsert_single_product(product: dict, graphql_url: str, headers: dict):
    """
    Create or update a product based on handle uniqueness.
    Returns: ("created"|"updated", user_errors_list)
    """
    mapped = map_product_to_productinput(product)
    # Add typed per-field metafields from the SOURCE product dict
    pmfs = _extras_to_typed_metafields(product, KNOWN_TOP_LEVEL_KEYS, namespace="plumbed")
    if pmfs:
        if isinstance(mapped.get("metafields"), list):
            mapped["metafields"] = mapped["metafields"] + pmfs
        else:
            mapped["metafields"] = pmfs

    # Normalize empty handle -> let Shopify generate one
    handle = (mapped.get("handle") or "").strip()
    if handle:
        handle = str(handle).lower().replace(" ", "-")   # normalize
        mapped["handle"] = handle
    else:
        mapped.pop("handle", None)
    
    mapped.pop("variants", None)
    mapped.pop("optionValues", None)

    existing_id = _get_product_id_by_handle(graphql_url, headers, handle) if handle else None

    if existing_id:
        mapped["id"] = existing_id
        mapped.pop("productOptions", None)
        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id handle }
            userErrors { field message }
          }
        }
        """
        resp = _graphqlexec(graphql_url, headers, mutation, {"input": mapped})
        user_errors = (((resp.get("data") or {}).get("productUpdate") or {}).get("userErrors")) or []
        return ("updated", user_errors)
    else:
        mapped.pop("optionValues", None)
        mapped.pop("productOptions", None)
        mutation = """
        mutation productCreate($input: ProductInput!) {
          productCreate(input: $input) {
            product { id handle }
            userErrors { field message }
          }
        }
        """
        resp = _graphqlexec(graphql_url, headers, mutation, {"input": mapped})
        user_errors = (((resp.get("data") or {}).get("productCreate") or {}).get("userErrors")) or []
        return ("created", user_errors)

def push_products_graphql_per_product(products, connection_params, mode_label="graphql"):
    graphql_url = connection_params["graphql_url"]
    access_token = connection_params["x_shopify_access_token"]
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": access_token}

    total_created_successfully = 0
    total_updated_successfully = 0
    total_failed = 0

    for batch_start_index in range(0, len(products), BATCH_SIZE):
        product_batch = products[batch_start_index:batch_start_index + BATCH_SIZE]
        batch_created = 0
        batch_updated = 0
        batch_failed = 0
        batch_sample_errors = []

        for product in product_batch:
            try:
                result, user_errors = _upsert_single_product(product, graphql_url, headers)
                if user_errors:
                    batch_failed += 1
                    if len(batch_sample_errors) < 3:
                        batch_sample_errors.append(", ".join(err.get("message", "") for err in user_errors))
                else:
                    if result == "created":
                        batch_created += 1
                    else:
                        batch_updated += 1
                if RATE_LIMIT_SLEEP > 0:
                    time.sleep(RATE_LIMIT_SLEEP)
            except requests.exceptions.RequestException as http_error:
                batch_failed += 1
                if len(batch_sample_errors) < 3:
                    batch_sample_errors.append(f"HTTP error: {http_error}")
            except Exception as e:
                batch_failed += 1
                if len(batch_sample_errors) < 3:
                    batch_sample_errors.append(str(e)[:200])

        total_created_successfully += batch_created
        total_updated_successfully += batch_updated
        total_failed += batch_failed

        logger.info({
            "severity": "INFO",
            "message": "batch_result",
            "mode": mode_label,
            "batch_start": batch_start_index,
            "batch_size": len(product_batch),
            "created_ok": batch_created,
            "updated_ok": batch_updated,
            "failed": batch_failed,
            "sample_errors": batch_sample_errors,
            "function": "push_products_graphql_per_product",
            "time": time.time()
        })

    logger.info({
        "severity": "INFO",
        "message": "upsert_done",
        "mode": mode_label,
        "total_created": total_created_successfully,
        "total_updated": total_updated_successfully,
        "total_failed": total_failed,
        "function": "push_products_graphql_per_product",
        "time": time.time()
    })

# ---------- Endpoint ----------
@app.route('/store_shopify_products', methods=['POST'])
def store_shopify_products():
    bearer_token = request.headers.get('Authorization')
    if not bearer_token:
        return jsonify({"error": "Authorization token is missing"}), 401

    # Verify caller
    try:
        plumbed_bearer_token_verification(bearer_token)
    except Exception as e:
        logger.error({
            "severity": "ERROR",
            "message": f"Authorization failed: {e}",
            "function": "store_shopify_products",
            "time": time.time()
        })
        return jsonify({"error": "Authorization failed"}), 401

    # Plumbed fetch mode (don't send 'auto')
    plumbed_sync_mode = (request.args.get('sync_mode') or 'full').strip().lower()

    try:
        products_from_plumbed = transfer_data_from_plumbed(bearer_token, plumbed_sync_mode)
        shopify_connection_params = get_connection_params(bearer_token)

        # Ensure metadata definition exists
        ensure_metadata_definition_exists_once(shopify_connection_params["graphql_url"], {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": shopify_connection_params["x_shopify_access_token"]
        })

        # Observability label only — we still create per-product via GraphQL in all cases
        mode_label = 'bulk' if len(products_from_plumbed) >= BULK_THRESHOLD else 'graphql'
        logger.info({
            "severity": "INFO",
            "message": "selected_mode",
            "mode": mode_label,
            "count": len(products_from_plumbed),
            "threshold": BULK_THRESHOLD,
            "function": "store_shopify_products",
            "time": time.time()
        })

        if plumbed_sync_mode == 'delete':
            # Not implemented yet
            return jsonify({"message": "Delete mode is not implemented yet"}), 200

        # Use bulk product creation if applicable
        if mode_label == 'bulk':
            bulk_product_create(products_from_plumbed, shopify_connection_params)
        else:
            # Always send per-product via GraphQL
            push_products_graphql_per_product(products_from_plumbed, shopify_connection_params, mode_label=mode_label)

        return jsonify({"message": "Data pushed to Shopify", "mode": mode_label, "count": len(products_from_plumbed)}), 200

    except requests.exceptions.RequestException as req_err:
        logger.error({
            "severity": "ERROR",
            "message": f"Network error occurred: {req_err}",
            "function": "store_shopify_products",
            "time": time.time()
        })
        return jsonify({"error": "Network error occurred"}), 500
    except ValueError as val_err:
        logger.error({
            "severity": "ERROR",
            "message": f"JSON parsing error: {val_err}",
            "function": "store_shopify_products",
            "time": time.time()
        })
        return jsonify({"error": "Invalid JSON response"}), 500
    except Exception as e:
        logger.error({
            "severity": "ERROR",
            "message": f"Error occurred: {e}",
            "function": "store_shopify_products",
            "time": time.time()
        })
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
