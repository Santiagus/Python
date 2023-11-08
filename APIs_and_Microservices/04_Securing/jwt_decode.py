from math import e
import jwt
import sys
from cryptography.x509 import load_pem_x509_certificate
from pathlib import Path

print("Token validation Use: python3 jwt_decode public_key.pem access_token")

public_key_text = Path("public_key.pem").read_text()
public_key = load_pem_x509_certificate(public_key_text.encode("utf-8")).public_key()
access_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguY29mZmVlbWVzaC5pby8iLCJzdWIiOiJlYzdiYmNjZi1jYTg5LTRhZjMtODJhYy1iNDFlNDgzMWE5NjIiLCJhdWQiOiJodHRwOi8vMTI3LjAuMC4xOjgwMDAvb3JkZXJzIiwiaWF0IjoxNjk5NDQzMTY1LjcyNjMxNywiZXhwIjoxNjk5NTI5NTY1LjcyNjMxNywic2NvcGUiOiJvcGVuaWQifQ.hpfxFqDtFz3KG0RQEoA0hBNyPbegnwKL76ZGuaGeLmdi7l61-MOfasQZzKTp6blYAspjF_E7N4nzd3al2RFMHQH9PGZznAD9_llKaSq3NRzNgOvabMOgCLxEaWKHcNAyiyo3vvlpHVsQjkhi-dH3V1mpiBxu_jA8EqvdU2w76_7YKxZowa38UddTi6UCXSdx6Psg8k_EIQRNklorDU1YLzPUHctdsbhtbNecstlmCWHwLYV_yc-KrlnH62c_4r1RpIBijtR1GW_nEW_nPQ_JE5iOzudZE78wbb3O6-XMWZzbvIfz03sCA1OwPhWnOhXqxdNLZVkHYJVIulkP-bgx9A"

if len(sys.argv) == 1:
    print("No params passed, using defaults")
    print("public_key.pem file : public_key.pem")
    print("access_token : ", access_token)
elif len(sys.argv) == 3:
    public_key_text = Path(sys.argv[1]).read_text()
    public_key = load_pem_x509_certificate(public_key_text.encode("utf-8")).public_key()
    access_token = sys.argv[2]

try:
    decode = jwt.decode(
        access_token,
        key=public_key,
        algorithms=["RS256"],
        audience=["http://127.0.0.1:8000/orders"],
    )
    print(decode)
except Exception as error:
    print("Decoding error : ", error)
