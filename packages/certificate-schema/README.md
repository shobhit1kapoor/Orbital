# ORBITAL Sigma certificate schema

The versioned `FlightCertificate` and `SafetyCase` schemas are implemented by
the shared Pydantic models and emitted as canonical JSON by CLEARANCE.

`public-keys/development.pub` is the Ed25519 verification key used for the
Phase 5 local acceptance evidence. The corresponding private key is generated
under the ignored `secrets/` directory and is never committed.
