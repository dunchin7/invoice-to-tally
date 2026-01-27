invoice_schema = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string"},
        "seller": {"type": "string"},
        "buyer": {"type": "string"},
        "currency": {"type": "string"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "total_price": {"type": "number"}
                },
                "required": ["description", "quantity", "unit_price", "total_price"]
            }
        },
        "subtotal": {"type": "number"},
        "tax": {"type": "number"},
        "total": {"type": "number"}
    },
    "required": [
        "invoice_number",
        "invoice_date",
        "seller",
        "buyer",
        "currency",
        "line_items",
        "subtotal",
        "tax",
        "total"
    ]
}
