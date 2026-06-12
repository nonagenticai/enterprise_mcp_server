# AA IaC demo manifest — intentionally insecure, used to live-fire the
# development_iac_security_patch AA card type (trivy-config iac_scanner).
# The open 0.0.0.0/0 SSH ingress trips trivy AWS-0107 (HIGH). The AA pipeline
# is expected to open a PR that restricts this rule.
resource "aws_security_group" "aa_iac_demo_open_ssh" {
  name        = "aa-iac-demo-open-ssh"
  description = "AA IaC demo SG (intentionally insecure)"
  vpc_id      = "vpc-aa-iac-demo"

  ingress {
    description = "SSH from anywhere (INSECURE)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    description = "all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}