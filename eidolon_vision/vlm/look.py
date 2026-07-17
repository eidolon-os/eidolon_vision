"""On-demand look (⑥): image + question -> text, via the house litellm layer.

This is the sync VLM face of the service — effectively the Explain backend.
It does NOT emit a sense.* fact; it returns text synchronously to the caller.
The concrete model behind litellm is a product/cost choice (config), not an
architecture choice.
"""

from __future__ import annotations

import base64


async def look(
    *, image_jpeg: bytes, question: str, model: str, temperature: float = 0.2
) -> str:
    """Ask a vision-capable model about a single JPEG frame; return its text answer."""
    import litellm  # lazy: keep import cost off the pure paths

    data_url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
    resp = await litellm.acompletion(
        model=model,
        temperature=temperature,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    )
    return resp["choices"][0]["message"]["content"] or ""
