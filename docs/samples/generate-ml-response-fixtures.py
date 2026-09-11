import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8001"

CASES = [
    ("mineguard-21-node-sample-request.json", "ml-response-21-node-normal.json"),
    ("mineguard-21-node-hardware-theft-test.json", "ml-response-21-node-hardware-theft.json"),
]

def post_json(path: Path):
    body = path.read_bytes()
    request = urllib.request.Request(
        BASE + "/predict",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)

for request_name, response_name in CASES:
    request_path = ROOT / "docs" / "samples" / request_name
    response_path = ROOT / "docs" / "samples" / response_name
    status, result = post_json(request_path)

    assert status == 200
    assert len(result["nodes"]) == 21
    assert set(result["nodes"][i]["node_id"] for i in range(21)) == {
        f"NODE-{i:03d}" for i in range(1, 22)
    }

    response_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{request_name}: HTTP {status}; "
        f"overall={result['overall']['status']}; "
        f"alarm={result['overall']['alarm']}; "
        f"anti_theft={result['anti_theft']['alert']}"
    )
