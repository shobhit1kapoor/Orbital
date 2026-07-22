package orbital.delegation

default allow := false

allow if {
  input.child_authority <= input.parent_authority
  input.child_risk_budget <= input.parent_remaining_risk_budget
  input.depth <= input.maximum_depth
  input.child_certified == true
  input.circular == false
}
