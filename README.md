# Hello-Brand-

Reference implementation of the three VAYA automation flows:

1. **Execute Programmatic Reward for Verified Purchase**
2. **Automate VAYA Identity and Wallet Provisioning**
3. **Process VAYA Play Winner Reward and Merchant Settlement**

## Run tests

```bash
python -m unittest -v
```

## Notes

- Uses SHA256 HMAC validation for inbound verified-purchase events.
- Models Celbux transaction types TT 1, TT 4, TT 18, TT 2011, and TT 2082 through a pluggable client interface.
- Publishes ROI/cultural momentum payloads to a pluggable Situation Room client.
