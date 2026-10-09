# autodl-tools

Small CLI for controlling AutoDL cloud GPU instances and tracking spend, built for freelance AI-media work where every idle hour is money.

## Why

Cloud GPU rentals bill by the hour and instances are easy to forget. This tool makes "shut it down when done, log what it cost" a two-command habit instead of a manual console hunt.

## Commands

```bash
python3 autodl_ctl.py balance              # wallet balance
python3 autodl_ctl.py list                 # list instances (run before starting work)
python3 autodl_ctl.py off <uuid> --job X   # power off + append a cost record
python3 autodl_ctl.py cost [--last N]      # spend summary
```

Cost records append to `logs/rental-costs.jsonl` (one JSON line each: stopped_at, uuid, name, started_at, duration_h, price_per_h, estimated cost, job tag).

## Credentials (two kinds, both outside git)

| Credential | Source | Scope |
|---|---|---|
| Developer token | AutoDL console → Account → Settings → Developer Token | `balance` (Pro API) |
| Web token | Browser devtools after console login (`localStorage.token`) | `list` / `off` (regular instances) |

## Notes from the field

- Wallet `assets` are in **li** (1/1000 CNY): `36780` = ¥36.78. Verified against the console.
- Regular container instances (`connect.*.seetacloud.com`) are **not** manageable via the Pro API — the developer token only sees `pro-`-prefixed instances. Regular instances use the console API (`www.autodl.com/api/v1/instance`), which accepts the web token.
- Pro API endpoints (`api.autodl.com/api/v1/dev/instance/pro/*`): create / power_on / power_off / release / status / snapshot / list.
- No public price-list endpoint exists (as of 2026-10); pricing is per-region/machine and only surfaces via instance snapshot or the console.
- Power-off stops GPU billing; system disk still bills daily. **Releasing an instance deletes its data.**

## License

MIT.
