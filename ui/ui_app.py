import os, requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response

load_dotenv()
STORE = os.environ["SHOPIFY_STORE_DOMAIN"]
MODE  = os.environ.get("SHOPIFY_API_MODE", "admin").lower()
SF_TOKEN = os.environ.get("SHOPIFY_STOREFRONT_TOKEN")
AD_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

app = Flask(__name__)

def endpoint_headers():
    if MODE == "admin":
        return (f"https://{STORE}/admin/api/2024-10/graphql.json",
                {"Content-Type":"application/json",
                 "X-Shopify-Access-Token":AD_TOKEN})
    else:
        return (f"https://{STORE}/api/2024-10/graphql.json",
                {"Content-Type":"application/json",
                 "X-Shopify-Storefront-Access-Token":SF_TOKEN})

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

# 本番は gunicorn で起動する（Dockerfileで設定）
