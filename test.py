from verifier import verify_claim

result = verify_claim(
    "India population is around 1.4 billion"
)

print(result["verification"])