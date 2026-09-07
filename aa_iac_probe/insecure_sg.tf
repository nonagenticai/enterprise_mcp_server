# AA IaC probe fixture. See aa_iac_probe/README.md.
#
# WHAT THIS DECLARES TODAY: one AWS security group, "aa-iac-probe-ssh", with a
# single ingress rule accepting TCP/22 from the CIDR block 0.0.0.0/0, and a
# single unrestricted egress rule.
#
# The acceptance oracle for this directory is check_iac.py. It pins the
# properties any change to this file must preserve; it does not prescribe the
# change. Run it with:  python -m aa_iac_probe.check_iac

resource "aws_security_group" "aa_iac_probe_ssh" {
  name        = "aa-iac-probe-ssh"
  description = "AA IaC probe security group"
  vpc_id      = "vpc-aa-iac-probe"

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
