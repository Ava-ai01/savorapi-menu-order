"""Ember & Oak Kitchen — Menu & Order Management REST API.

A small, dependency-light REST API that powers online ordering for a
restaurant's website or mobile app: menu management (CRUD) plus order
intake with automatic price calculation and status tracking.

Run with:
    python app.py        # starts on http://127.0.0.1:5000
    # or: flask --app app run

All responses are JSON — including errors, which always look like:
    {"error": "human-readable message"}
with an appropriate HTTP status code (400 validation, 404 missing,
405 wrong method). Storage is in-memory; restarting resets the seed menu.
"""
from copy import deepcopy
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
MENU_CATEGORIES = {"starter", "main", "dessert", "drink"}
ORDER_STATUSES = {"received", "preparing", "ready", "completed", "cancelled"}


# ---------------------------------------------------------------------------
# Seed data — a realistic restaurant menu across four categories
# ---------------------------------------------------------------------------
def seed_menu():
    """Return a fresh copy of the demo menu."""
    return [
        {"id": 1, "name": "Fire-Baked Sourdough", "description": "Blistered in the wood oven, whipped smoked butter, flaky salt", "price": 8.00, "category": "starter", "available": True},
        {"id": 2, "name": "Burrata & Charred Stone Fruit", "description": "Creamy burrata, fire-kissed peaches, basil oil, aged balsamic", "price": 16.00, "category": "starter", "available": True},
        {"id": 3, "name": "Grilled Octopus", "description": "Oak-grilled tentacle, crispy fingerlings, smoked paprika aioli", "price": 21.00, "category": "starter", "available": True},
        {"id": 4, "name": "Oak-Fired Ribeye", "description": "28-day dry-aged, roasted bone marrow butter, watercress", "price": 46.00, "category": "main", "available": True},
        {"id": 5, "name": "Half Chicken al Mattone", "description": "Brick-pressed heritage chicken, charred lemon, rosemary jus", "price": 32.00, "category": "main", "available": True},
        {"id": 6, "name": "Wild Mushroom Risotto", "description": "Carnaroli rice, foraged chanterelles, pecorino, truffle oil", "price": 27.00, "category": "main", "available": True},
        {"id": 7, "name": "Cedar Plank Salmon", "description": "Faroe Island salmon, miso glaze, charred scallions, sesame", "price": 34.00, "category": "main", "available": True},
        {"id": 8, "name": "Dark Chocolate Budino", "description": "Olive oil, smoked sea salt, ember-toasted hazelnuts", "price": 13.00, "category": "dessert", "available": True},
        {"id": 9, "name": "Burnt Honey Panna Cotta", "description": "Caramelized honey, macerated berries, almond crumble", "price": 12.00, "category": "dessert", "available": True},
        {"id": 10, "name": "Wood-Oven Affogato", "description": "Vanilla bean gelato drowned in double espresso, amaretti", "price": 10.00, "category": "dessert", "available": True},
        {"id": 11, "name": "Smoked Old Fashioned", "description": "Oak-smoked bourbon, demerara, black walnut bitters", "price": 15.00, "category": "drink", "available": True},
        {"id": 12, "name": "House Red — Willamette Pinot Noir", "description": "Glass pour from our natural wine list, rotating producer", "price": 14.00, "category": "drink", "available": True},
    ]


menu_items = seed_menu()
next_menu_id = 13
orders = []
next_order_id = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def error(message, status):
    """Return a consistent JSON error response with the given HTTP status."""
    return jsonify({"error": message}), status


def find_menu(item_id):
    """Find a menu item by id, or None."""
    return next((m for m in menu_items if m["id"] == item_id), None)


def find_order(order_id):
    """Find an order by id, or None."""
    return next((o for o in orders if o["id"] == order_id), None)


def validate_menu_payload(data, partial=False):
    """Validate a menu-item payload; return (clean_item, error_message)."""
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    required = {"name", "price", "category"}
    if not partial:
        missing = required - set(data.keys())
        if missing:
            return None, f"Missing required fields: {', '.join(sorted(missing))}."
    elif not any(k in data for k in ("name", "description", "price", "category", "available")):
        return None, "No updatable fields provided."

    item = {}
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            return None, "'name' must be a non-empty string."
        item["name"] = name.strip()
    if "description" in data:
        desc = data["description"]
        if not isinstance(desc, str):
            return None, "'description' must be a string."
        item["description"] = desc
    if "price" in data:
        price = data["price"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            return None, "'price' must be a positive number."
        item["price"] = round(float(price), 2)
    if "category" in data:
        if data["category"] not in MENU_CATEGORIES:
            return None, f"'category' must be one of: {', '.join(sorted(MENU_CATEGORIES))}."
        item["category"] = data["category"]
    if "available" in data:
        if not isinstance(data["available"], bool):
            return None, "'available' must be true or false."
        item["available"] = data["available"]
    return item, None


def build_order(customer_name, line_items):
    """Resolve line items against the menu and compute line/total prices.

    Returns (order_body, None) on success, or (None, error_message).
    """
    resolved = []
    total = 0.0
    for entry in line_items:
        if not isinstance(entry, dict) or "menu_id" not in entry:
            return None, "Each item must be an object with 'menu_id' (and optional 'quantity')."
        menu_id = entry["menu_id"]
        quantity = entry.get("quantity", 1)
        if not isinstance(quantity, int) or quantity < 1:
            return None, f"'quantity' for menu_id {menu_id} must be a positive integer."
        dish = find_menu(menu_id)
        if dish is None:
            return None, f"No menu item with id {menu_id}."
        if not dish["available"]:
            return None, f"'{dish['name']}' is currently unavailable."
        line_total = round(dish["price"] * quantity, 2)
        total += line_total
        resolved.append({
            "menu_id": dish["id"],
            "name": dish["name"],
            "unit_price": dish["price"],
            "quantity": quantity,
            "line_total": line_total,
        })
    return {"customer_name": customer_name, "items": resolved, "total": round(total, 2)}, None


# ---------------------------------------------------------------------------
# Root / docs
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """GET / — service identity and where to find the docs."""
    return jsonify({
        "service": "Ember & Oak Kitchen — Menu & Order API",
        "version": "1.0.0",
        "docs": "/api/docs",
    })


@app.route("/api/docs")
def docs():
    """GET /api/docs — machine-readable endpoint list with examples."""
    return jsonify({
        "service": "Ember & Oak Kitchen — Menu & Order API",
        "version": "1.0.0",
        "endpoints": [
            {"method": "GET", "path": "/api/menu", "description": "List all menu items. Optional query param: ?category=main"},
            {"method": "POST", "path": "/api/menu", "description": "Create a menu item. Body: name, price, category, optional description, available"},
            {"method": "GET", "path": "/api/menu/<id>", "description": "Get one menu item by id"},
            {"method": "PUT", "path": "/api/menu/<id>", "description": "Replace a menu item (full payload required)"},
            {"method": "DELETE", "path": "/api/menu/<id>", "description": "Delete a menu item"},
            {"method": "GET", "path": "/api/orders", "description": "List all orders. Optional query param: ?status=preparing"},
            {"method": "POST", "path": "/api/orders", "description": "Create an order. Body: customer_name, items: [{menu_id, quantity?}]"},
            {"method": "GET", "path": "/api/orders/<id>", "description": "Get one order by id"},
            {"method": "PATCH", "path": "/api/orders/<id>", "description": "Update order status. Body: {status: received|preparing|ready|completed|cancelled}"},
        ],
        "examples": {
            "create_menu_item": {
                "request": "POST /api/menu  {\"name\": \"Heirloom Tomato Salad\", \"price\": 15.00, \"category\": \"starter\"}",
                "response_status": 201,
            },
            "create_order": {
                "request": "POST /api/orders  {\"customer_name\": \"Jane Doe\", \"items\": [{\"menu_id\": 4, \"quantity\": 2}, {\"menu_id\": 11}]}",
                "response_status": 201,
            },
        },
        "full_docs": "See README.md for the complete endpoint reference with curl examples.",
    })


# ---------------------------------------------------------------------------
# Menu endpoints
# ---------------------------------------------------------------------------
@app.route("/api/menu", methods=["GET"])
def list_menu():
    """GET /api/menu — list menu items, optionally filtered by ?category=."""
    category = request.args.get("category")
    items = menu_items
    if category:
        if category not in MENU_CATEGORIES:
            return error(f"'category' must be one of: {', '.join(sorted(MENU_CATEGORIES))}.", 400)
        items = [m for m in menu_items if m["category"] == category]
    return jsonify({"items": items, "count": len(items)})


@app.route("/api/menu/<int:item_id>", methods=["GET"])
def get_menu_item(item_id):
    """GET /api/menu/<id> — fetch a single menu item (404 if missing)."""
    item = find_menu(item_id)
    if item is None:
        return error(f"No menu item with id {item_id}.", 404)
    return jsonify(item)


@app.route("/api/menu", methods=["POST"])
def create_menu_item():
    """POST /api/menu — create a menu item; 201 on success, 400 on bad input."""
    global next_menu_id
    data = request.get_json(silent=True)
    if data is None:
        return error("Request body must be valid JSON.", 400)
    item, err = validate_menu_payload(data)
    if err:
        return error(err, 400)
    item.setdefault("description", "")
    item.setdefault("available", True)
    item["id"] = next_menu_id
    next_menu_id += 1
    menu_items.append(item)
    return jsonify(item), 201


@app.route("/api/menu/<int:item_id>", methods=["PUT"])
def replace_menu_item(item_id):
    """PUT /api/menu/<id> — full replacement of a menu item (404 if missing)."""
    item = find_menu(item_id)
    if item is None:
        return error(f"No menu item with id {item_id}.", 404)
    data = request.get_json(silent=True)
    if data is None:
        return error("Request body must be valid JSON.", 400)
    new_item, err = validate_menu_payload(data)
    if err:
        return error(err, 400)
    new_item.setdefault("description", "")
    new_item.setdefault("available", True)
    new_item["id"] = item_id
    item.clear()
    item.update(new_item)
    return jsonify(item)


@app.route("/api/menu/<int:item_id>", methods=["DELETE"])
def delete_menu_item(item_id):
    """DELETE /api/menu/<id> — remove a menu item (204 on success)."""
    item = find_menu(item_id)
    if item is None:
        return error(f"No menu item with id {item_id}.", 404)
    menu_items.remove(item)
    return "", 204


# ---------------------------------------------------------------------------
# Order endpoints
# ---------------------------------------------------------------------------
@app.route("/api/orders", methods=["GET"])
def list_orders():
    """GET /api/orders — list orders, optionally filtered by ?status=."""
    status = request.args.get("status")
    result = orders
    if status:
        if status not in ORDER_STATUSES:
            return error(f"'status' must be one of: {', '.join(sorted(ORDER_STATUSES))}.", 400)
        result = [o for o in orders if o["status"] == status]
    return jsonify({"orders": result, "count": len(result)})


@app.route("/api/orders", methods=["POST"])
def create_order():
    """POST /api/orders — create an order; prices resolved server-side, 201 on success."""
    global next_order_id
    data = request.get_json(silent=True)
    if data is None:
        return error("Request body must be valid JSON.", 400)
    customer_name = data.get("customer_name")
    if not isinstance(customer_name, str) or not customer_name.strip():
        return error("'customer_name' must be a non-empty string.", 400)
    line_items = data.get("items")
    if not isinstance(line_items, list) or not line_items:
        return error("'items' must be a non-empty list of {menu_id, quantity}.", 400)
    order_body, err = build_order(customer_name.strip(), line_items)
    if err:
        return error(err, 400)
    order = {"id": next_order_id, "status": "received", **order_body}
    next_order_id += 1
    orders.append(order)
    return jsonify(order), 201


@app.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    """GET /api/orders/<id> — fetch a single order (404 if missing)."""
    order = find_order(order_id)
    if order is None:
        return error(f"No order with id {order_id}.", 404)
    return jsonify(order)


@app.route("/api/orders/<int:order_id>", methods=["PATCH"])
def update_order_status(order_id):
    """PATCH /api/orders/<id> — advance an order's status (received→…→completed)."""
    order = find_order(order_id)
    if order is None:
        return error(f"No order with id {order_id}.", 404)
    data = request.get_json(silent=True)
    if data is None:
        return error("Request body must be valid JSON.", 400)
    status = data.get("status")
    if status not in ORDER_STATUSES:
        return error(f"'status' must be one of: {', '.join(sorted(ORDER_STATUSES))}.", 400)
    order["status"] = status
    return jsonify(order)


# ---------------------------------------------------------------------------
# Error handlers — always JSON, never HTML
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return error("Not found.", 404)


@app.errorhandler(405)
def method_not_allowed(_e):
    return error("Method not allowed for this endpoint.", 405)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
