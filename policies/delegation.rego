package orbital.delegation

default allow := false

allow if {
  input.child_authority <= input.parent_authority
  input.delegated_authority <= input.parent_authority
  input.delegated_risk_budget <= input.parent_remaining_risk_budget
  input.depth <= input.maximum_depth
  input.parent_certificate_valid == true
  input.child_certificate_valid == true
  input.parent_identity_matches == true
  input.child_identity_matches == true
  input.same_tenant == true
  input.data_labels_allowed == true
  input.shared_memory_isolated == true
  input.circular == false
  input.prohibited_tool == false
  input.tool_authority_sufficient == true
  input.not_expired == true
  input.ownership_present == true
  every tool in input.delegated_tools {
    tool in input.parent_allowed_tools
    tool in input.child_allowed_tools
  }
}
