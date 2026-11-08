"""Allowlisted, read-only agent tools. No fabricated real-time statistics."""


def get_market_trends(topic: str) -> str:
    topic = str(topic).strip()[:120]
    return (
        f"برای موضوع «{topic}» در این سرویس داده آماری زنده یا ابزار تحلیل بازار متصل نیست. "
        "می‌توانم روش تحقیق کلمات کلیدی، تحلیل رقبا و منابع سنجش روند را پیشنهاد بدهم، "
        "اما عدد رشد یا حجم جستجو را بدون منبع معتبر اعلام نمی‌کنم."
    )


def generate_caption(product: str) -> str:
    product = str(product).strip()[:120]
    return (
        f"🌟 با {product} یک قدم به تجربه بهتر نزدیک شوید.\n"
        "برای آشنایی با جزئیات و انتخاب مناسب، به ما پیام بدهید.\n"
        "#راستیناکس #دیجیتال_مارکتینگ"
    )


tools_schema = [
    {"type": "function", "function": {"name": "get_market_trends",
     "description": "Explain market research options without claiming live statistics",
     "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}},
    {"type": "function", "function": {"name": "generate_caption",
     "description": "Generate a brief Persian marketing caption",
     "parameters": {"type": "object", "properties": {"product": {"type": "string"}}, "required": ["product"]}}},
]

available_tools = {"get_market_trends": get_market_trends, "generate_caption": generate_caption}


def call_tool(name: str, arguments: str) -> str:
    import json
    if name not in available_tools:
        return "ابزار در دسترس نیست."
    try:
        args = json.loads(arguments)
        required = "topic" if name == "get_market_trends" else "product"
        if not isinstance(args, dict) or not isinstance(args.get(required), str):
            return "پارامتر ابزار نامعتبر است."
        value = args[required].strip()
        if not value or len(value) > 120:
            return "طول پارامتر ابزار مجاز نیست."
        return available_tools[name](value)
    except (ValueError, TypeError):
        return "پارامتر ابزار نامعتبر است."
