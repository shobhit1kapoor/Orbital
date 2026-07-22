package orbital.privacy

default allow_export := false

sensitive_keys := {
  "customer_name",
  "customer_email",
  "raw_prompt",
  "chain_of_thought",
  "capability_token",
  "payment_credentials",
}

allow_export if {
  count({key | some key in object.keys(input.attributes); key in sensitive_keys}) == 0
}
