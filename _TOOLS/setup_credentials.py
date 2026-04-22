import sys, getpass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

raw = getpass.getpass("Paste MetaMask private key (hidden): ").strip()
key = raw.replace("0x","").replace(" ","").strip()

if len(key) != 64:
    print(f"ERROR: Key is {len(key)} chars, needs 64. Check MetaMask export.")
    sys.exit(1)

print(f"Key OK ({len(key)} chars). Connecting...")

try:
    from py_clob_client.client import ClobClient
    client = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=key)
    creds = client.create_or_derive_api_creds()
    print(f"Creds type: {type(creds)}")
    print(f"Creds: {creds}")

    try: ak, sk, pk = creds["apiKey"], creds["secret"], creds["passphrase"]
    except: ak, sk, pk = creds.api_key, creds.api_secret, creds.api_passphrase

    with open(".env","w") as f:
        f.write(f"POLY_PRIVATE_KEY={key}\nPOLY_API_KEY={ak}\nPOLY_API_SECRET={sk}\nPOLY_PASSPHRASE={pk}\n")
    print("SUCCESS - .env written. Run: python agent\main.py")
except Exception as e:
    import traceback; traceback.print_exc()
