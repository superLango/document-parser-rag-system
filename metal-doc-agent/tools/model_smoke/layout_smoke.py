"""Layout API smoke test: send one page image, print detected blocks.

Run on the model host (or any host that can reach 9978):
    python tools/model_smoke/layout_smoke.py --image /tmp/glm_smoke_page.png
"""

from __future__ import annotations

import argparse
import base64
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:9978/v1/layout")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--out", default="/tmp/layout_smoke.json")
    args = parser.parse_args()

    image_b64 = base64.b64encode(open(args.image, "rb").read()).decode("ascii")
    resp = httpx.post(
        args.url,
        json={
            "page_index": args.page,
            "dpi": args.dpi,
            "image_base64": image_b64,
        },
        timeout=300,
    )
    print("HTTP", resp.status_code)
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("blocks", [])
    print("blocks", len(blocks))
    print("types", sorted({block["type"] for block in blocks}))
    print("has_table", any(block["type"] == "table" for block in blocks))
    print("page_failures", data.get("page_failures"))
    for block in blocks[:8]:
        print(block["order"], block["type"], block["bbox"], block["confidence"])
    open(args.out, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
