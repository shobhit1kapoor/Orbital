package orbital.refund

default allow := false

allow if {
  input.tool == "lookup_order"
  delegation_authorized
}

allow if {
  input.tool == "issue_refund"
  input.order_verified == true
  input.amount > 0
  input.amount <= input.amount_paid
  input.amount <= input.certificate_maximum_amount
  input.artifact_digest == input.certificate_artifact_digest
  input.telemetry_complete == true
  not approval_required
  delegation_authorized
}

allow if {
  input.tool == "issue_refund"
  input.order_verified == true
  input.amount > 0
  input.amount <= input.amount_paid
  input.amount <= input.certificate_maximum_amount
  input.artifact_digest == input.certificate_artifact_digest
  input.telemetry_complete == true
  approval_required
  input.human_approved == true
  delegation_authorized
}

delegation_authorized if {
  not input.delegation_id
}

delegation_authorized if {
  input.delegation_id
  input.delegation_allowed == true
  input.delegation_evidence_state == "CONFIRMED"
}

approval_required if {
  input.amount > input.human_approval_above
}

reason := "order_not_verified" if {
  input.order_verified != true
}

reason := "amount_exceeds_payment" if {
  input.amount > input.amount_paid
}

reason := "amount_exceeds_certificate" if {
  input.amount > input.certificate_maximum_amount
}

reason := "artifact_mismatch" if {
  input.artifact_digest != input.certificate_artifact_digest
}

reason := "human_approval_required" if {
  approval_required
  input.human_approved != true
}

reason := "missing_telemetry" if {
  input.telemetry_complete != true
}
