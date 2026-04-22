import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def main() -> int:
    env_path = Path(".env")
    if not env_path.exists():
        return fail(".env was not found in this folder. Copy from .env.example first.")

    load_dotenv(dotenv_path=env_path)

    account_name = os.getenv("ACCOUNT_NAME", "").strip()
    private_key = os.getenv("POLY_PRIVATE_KEY", "").strip().replace("0x", "")
    signer_address = os.getenv("POLY_SIGNER_ADDRESS", "").strip()
    funder_address = os.getenv("POLY_FUNDER_ADDRESS", "").strip()
    signature_type_raw = os.getenv("POLY_SIGNATURE_TYPE", "0").strip()

    if not private_key:
        return fail("POLY_PRIVATE_KEY is empty.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", private_key):
        return fail("POLY_PRIVATE_KEY must be exactly 64 hex chars with no 0x prefix.")

    try:
        signature_type = int(signature_type_raw)
    except ValueError:
        return fail("POLY_SIGNATURE_TYPE must be an integer (0, 1, or 2).")

    derived_signer = Account.from_key("0x" + private_key).address

    print("---- ENV SUMMARY ----")
    print(f"ACCOUNT_NAME: {account_name or '(not set)'}")
    print(f"POLY_SIGNER_ADDRESS (env): {signer_address or '(not set)'}")
    print(f"POLY_SIGNER_ADDRESS (derived): {derived_signer}")
    print(f"POLY_FUNDER_ADDRESS: {funder_address or '(empty)'}")
    print(f"POLY_SIGNATURE_TYPE: {signature_type}")

    if signer_address and signer_address.lower() != derived_signer.lower():
        return fail("POLY_SIGNER_ADDRESS does not match the address derived from POLY_PRIVATE_KEY.")

    mode_map = {0: "EOA (MetaMask standard wallet)", 1: "POLY_PROXY (Magic Link)", 2: "GNOSIS_SAFE proxy"}
    detected_mode = mode_map.get(signature_type, "Unknown")
    print(f"Detected mode: {detected_mode}")

    if signature_type in (1, 2) and not funder_address:
        return fail("POLY_FUNDER_ADDRESS is required for signature type 1 or 2.")

    try:
        from py_clob_client.client import ClobClient
    except Exception as exc:
        return fail(f"py_clob_client import failed: {exc}")

    def try_auth(sig_t: int, funder: str):
        try:
            if sig_t in (1, 2):
                c = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=137,
                    key=private_key,
                    signature_type=sig_t,
                    funder=funder,
                )
            else:
                c = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=137,
                    key=private_key,
                )
            creds_local = c.create_or_derive_api_creds()
            c.set_api_creds(creds_local)
            return True, c, creds_local, None
        except Exception as ex:
            return False, None, None, str(ex)

    ok, client, creds, auth_error = try_auth(signature_type, funder_address)
    if not ok:
        print(f"Primary auth attempt failed: {auth_error}")
        print("Trying fallback signature profiles...")
        fallback_profiles = []
        if funder_address:
            fallback_profiles.extend([(2, funder_address), (1, funder_address)])
        fallback_profiles.append((0, ""))
        # Avoid duplicate first attempt
        fallback_profiles = [p for p in fallback_profiles if not (p[0] == signature_type and p[1] == funder_address)]

        for sig_t, funder in fallback_profiles:
            ok2, client2, creds2, err2 = try_auth(sig_t, funder)
            if ok2:
                print(f"Fallback SUCCESS with signature_type={sig_t} funder={'set' if funder else 'empty'}")
                print("Update your .env to use this signature_type/funder combination.")
                client = client2
                creds = creds2
                ok = True
                break
            print(f"Fallback failed for signature_type={sig_t}: {err2}")

    if not ok:
        return fail("All auth attempts failed. Recheck wallet mode, funder, and private key.")

    key_preview = None
    if isinstance(creds, dict):
        key_preview = creds.get("apiKey")
    else:
        key_preview = getattr(creds, "api_key", None)
    if key_preview:
        print(f"CLOB auth OK. API key prefix: {str(key_preview)[:8]}")
    else:
        print("CLOB auth OK. API creds derived.")

    read_test_done = False
    for fn_name in ("get_positions", "get_trades", "get_orders", "get_balance_allowance", "get_balance"):
        if not hasattr(client, fn_name):
            continue
        fn = getattr(client, fn_name)
        try:
            data = fn()
            preview = str(type(data).__name__)
            if isinstance(data, list):
                preview += f" (rows={len(data)})"
            print(f"Read test OK via {fn_name}: {preview}")
            read_test_done = True
            break
        except TypeError:
            # Some client versions require args for certain methods.
            continue
        except Exception as exc:
            print(f"Read test method {fn_name} failed: {exc}")
            continue

    if not read_test_done:
        print("Read test skipped (no zero-arg read method succeeded), but CLOB auth passed.")

    print("PASS: .env is linked well enough for this agent to attempt live CLOB usage.")
    print("Tip: keep DRY_RUN=1 until you verify dashboard identity + live portfolio panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
