# MineGuard API Sample JSON

These fixtures are for Web/App development against the MineGuard ML API.

## Request fixtures

- `mineguard-21-node-sample-request.json`
- `mineguard-21-node-hardware-theft-test.json`

Send them to:

`POST http://localhost:8001/predict`

## Verified response fixtures

- `ml-response-21-node-normal.json`
- `ml-response-21-node-hardware-theft.json`

These response files are the actual serialized responses returned by the production ML pipeline when the corresponding request fixture was posted to `/predict`.

### Important

The `normal` filename refers to the normal/source fixture name. Its actual current API result is:

- `overall.status`: `WARNING`
- `overall.alarm`: `true`
- `anti_theft.alert`: `false`

The hardware-theft fixture's result is:

- `overall.status`: `WARNING`
- `overall.alarm`: `true`
- `anti_theft.alert`: `true`
- `anti_theft.status`: `THEFT_SUSPECTED`
- `anti_theft.affected_node_ids`: `["NODE-001"]`

Do not manually change the response fixtures to make them look normal. The API response is the source of truth.

## Windows PowerShell

```powershell
$body = Get-Content -Raw .\docs\samples\mineguard-21-node-sample-request.json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" -Body $body

$body = Get-Content -Raw .\docs\samples\mineguard-21-node-hardware-theft-test.json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" -Body $body
```

## Frontend/mobile

Use the same JSON object as the request body in `fetch`, Axios, Retrofit, Dio, etc. The client should only render the returned ML response and must not recalculate risk, anomaly, deformation, threshold times, Haversine distance, or anti-theft confirmation.
