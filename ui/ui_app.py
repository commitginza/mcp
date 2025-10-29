import os, requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response, abort
from flask_cors import CORS

load_dotenv()

STORE = os.environ["SHOPIFY_STORE_DOMAIN"]
MODE  = os.environ.get("SHOPIFY_API_MODE", "admin").lower()
SF_TOKEN = os.environ.get("SHOPIFY_STOREFRONT_TOKEN")
AD_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

# 任意: ChatGPT Actions 等向けのAPIキー。設定されている場合のみ必須化。
ACTIONS_API_KEY = os.environ.get("ACTIONS_API_KEY")

app = Flask(__name__)
# 必要に応じてCORS許可（Actionsはサーバ間通信なので不要だが、ブラウザ検証時に便利）
CORS(app, resources={r"/api/*": {"origins": "*"}})

def endpoint_headers():
    if MODE == "admin":
        return (f"https://{STORE}/admin/api/2024-10/graphql.json",
                {"Content-Type":"application/json",
                 "X-Shopify-Access-Token":AD_TOKEN})
    else:
        return (f"https://{STORE}/api/2024-10/graphql.json",
                {"Content-Type":"application/json",
                 "X-Shopify-Storefront-Access-Token":SF_TOKEN})

@app.before_request
def _require_api_key_if_configured():
    # /healthz と /openapi.json は常に許可
    if request.path in ("/healthz", "/openapi.json"):
        return
    # APIキーが設定されていなければスキップ
    if not ACTIONS_API_KEY:
        return
    # /api/ 以下のみ保護（必要なら範囲を広げる）
    if request.path.startswith("/api/"):
        api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if api_key != ACTIONS_API_KEY:
            return jsonify({"error":"unauthorized"}), 401

@app.errorhandler(Exception)
def _on_error(e):
    code = getattr(e, "code", 500)
    return jsonify({"error": str(e)}), code

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.get("/api/search")
def api_search():
    q_raw = (request.args.get("q") or "").strip()
    limit = max(1, min(int(request.args.get("limit", "100")), 50))
    fallback = request.args.get("fallback") is not None

    url, headers = endpoint_headers()

    # Fallback or empty → Admin: status:active AND inventory_total>0 の上位 N
    if fallback or not q_raw:
        if MODE == "admin":
            gql = """
            query ($first:Int!) {
              products(first:$first, query:"status:active AND inventory_total:>0") {
                edges { node {
                  title handle vendor productType onlineStoreUrl
                  variants(first:50) { edges { node { price inventoryQuantity } } }
                  images(first:1) { edges { node { src altText } } }
                } }
              }
            }"""
            variables = {"first": limit}
        else:
            gql = """
            query ($first:Int!) {
              products(first:$first) {
                edges { node {
                  title handle vendor productType onlineStoreUrl availableForSale
                  variants(first:50) { edges { node {
                    price { amount currencyCode } quantityAvailable availableForSale
                  } } }
                  images(first:1) { edges { node { url altText } } }
                } }
              }
            }"""
            variables = {"first": limit}
    else:
        # 検索語を分解して OR 検索式へ
        terms = {t for t in q_raw.replace("　"," ").split(" ") if t}
        frags = []
        for t in terms:
            frags += [f"title:*{t}*", f"tag:{t}", f"product_type:*{t}*", f"vendor:*{t}*"]
        q = " OR ".join(frags)
        if MODE == "admin":
            q = f"({q}) AND inventory_total:>0"
            gql = """
            query ($q:String!, $first:Int!) {
              products(first:$first, query:$q) {
                edges { node {
                  title handle vendor productType onlineStoreUrl
                  variants(first:50) { edges { node { price inventoryQuantity } } }
                  images(first:1) { edges { node { src altText } } }
                } }
              }
            }"""
        else:
            gql = """
            query ($q:String!, $first:Int!) {
              products(first:$first, query:$q) {
                edges { node {
                  title handle vendor productType onlineStoreUrl availableForSale
                  variants(first:50) { edges { node {
                    price { amount currencyCode } quantityAvailable availableForSale
                  } } }
                  images(first:1) { edges { node { url altText } } }
                } }
              }
            }"""
        variables = {"q": q, "first": limit}

    r = requests.post(url, headers=headers, json={"query": gql, "variables": variables}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "errors" in j: return jsonify(j), 400

    out=[]
    edges = j.get("data",{}).get("products",{}).get("edges",[]) or []
    for e in edges:
        n = e["node"]
        v_edges = (n.get("variants",{}).get("edges") or [])
        qty, price = 0, None
        for ve in v_edges:
            vn = ve["node"]
            price = vn.get("price") or price
            qty += int((vn.get("inventoryQuantity") if MODE=="admin" else vn.get("quantityAvailable")) or 0)

        # 在庫>0のみ
        if qty < 1: continue
        if MODE != "admin":
            if not n.get("availableForSale"): continue

        img_edges = (n.get("images",{}).get("edges") or [])
        img = None
        if img_edges:
            node = img_edges[0]["node"]
            img = {"url": node.get("src") or node.get("url"), "alt": node.get("altText")}

        out.append({
            "title": n.get("title"),
            "url": n.get("onlineStoreUrl") or f"https://{STORE}/products/{n.get('handle')}",
            "vendor": n.get("vendor"),
            "productType": n.get("productType"),
            "inventory": qty,
            "price": price if isinstance(price, dict) else {"amount": price, "currencyCode": None},
            "image": img
        })
    return jsonify(out)

@app.get("/openapi.json")
def openapi_json():
    """
    ChatGPT Actions 用の OpenAPI 3.0 スキーマを動的生成。
    operationId 必須、application/json のみ、複雑な schema 合成を不使用。
    """
    server_url = request.url_root.rstrip("/")
    spec = {
      "openapi": "3.0.3",
      "info": {
        "title": "Shopify Product Search API",
        "version": "1.0.0",
        "description": "在庫あり商品の検索API。UIと同一ホストで提供。"
      },
      "servers": [{"url": server_url}],
      "paths": {
        "/api/search": {
          "get": {
            "operationId": "searchProducts",
            "summary": "商品検索",
            "description": "クエリ語でShopify商品を検索。未指定またはfallback時は在庫ありの上位を返す。",
            "parameters": [
              {"name":"q","in":"query","required":False,
               "schema":{"type":"string"}, "description":"検索語。スペース区切り。"},
              {"name":"limit","in":"query","required":False,
               "schema":{"type":"integer","minimum":1,"maximum":50,"default":100},
               "description":"最大件数（1〜50）"},
              {"name":"fallback","in":"query","required":False,
               "schema":{"type":"string"},
               "description":"存在するだけでfallback検索を有効化"}
            ],
            "responses": {
              "200": {
                "description": "検索結果",
                "content": {
                  "application/json": {
                    "schema": {
                      "type":"array",
                      "items":{"$ref":"#/components/schemas/Product"}
                    }
                  }
                }
              },
              "400": {"description":"不正リクエスト"},
              "401": {"description":"未認証"},
              "500": {"description":"サーバエラー"}
            },
            "security": ([{"ApiKeyAuth": []}] if ACTIONS_API_KEY else [])
          }
        }
      },
      "components": {
        "schemas": {
          "Money": {
            "type":"object",
            "properties":{
              "amount":{"type":"number"},
              "currencyCode":{"type":["string","null"]}
            },
            "required":["amount","currencyCode"]
          },
          "Image": {
            "type":"object",
            "properties":{
              "url":{"type":["string","null"]},
              "alt":{"type":["string","null"]}
            }
          },
          "Product": {
            "type":"object",
            "properties":{
              "title":{"type":["string","null"]},
              "url":{"type":["string","null"]},
              "vendor":{"type":["string","null"]},
              "productType":{"type":["string","null"]},
              "inventory":{"type":"integer"},
              "price":{"$ref":"#/components/schemas/Money"},
              "image":{"$ref":"#/components/schemas/Image"}
            },
            "required":["title","url","inventory","price"]
          }
        },
        "securitySchemes": ({
          "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "環境変数 ACTIONS_API_KEY が設定されている場合に必須"
          }
        } if ACTIONS_API_KEY else {})
      }
    }
    return jsonify(spec)
