# Infrastructure Integration

This directory contains all Terraform modules and Ansible playbooks integrated with the AegisOps dynamic workflow system.

## Overview

The infrastructure integration enables **zero-code-change** addition of new service requests. Simply add:
1. Terraform module or Ansible playbook
2. Workflow JSON definition
3. Pydantic schema (optional)

The agent orchestration system will automatically discover and execute the new workflows.

## Directory Structure

```
infrastructure/
├── terraform/           # Terraform modules for cloud provisioning
│   ├── aws/            # AWS resources (EC2, EKS, VPC, RDS, KMS, LB)
│   ├── azure/          # Azure resources
│   └── gcp/            # GCP resources
└── ansible/            # Ansible playbooks for Day-2 operations
    ├── aws/            # AWS playbooks
    ├── azure/          # Azure playbooks
    ├── gcp/            # GCP playbooks
    └── k8s/            # Kubernetes operations
```

## Available Terraform Modules

### AWS
- **EC2**: Provision EC2 instances with customizable AMI, instance type, storage
- **EKS**: Deploy managed Kubernetes clusters with node groups
- **VPC**: Create VPCs with subnets, IGW, route tables, NAT gateways
- **RDS**: Provision RDS database instances (PostgreSQL, MySQL, etc.)
- **KMS**: Manage encryption keys
- **LB**: Configure Application and Network Load Balancers

### Azure
- Similar resources for Azure cloud

### GCP
- Similar resources for Google Cloud Platform

## Available Ansible Playbooks

### AWS
- `aws-ec2.yml`: EC2 instance provisioning and configuration
- `aws-eks.yml`: EKS cluster deployment
- `aws-vpc.yml`: VPC network configuration
- `aws-kms.yml`: KMS key management

### Kubernetes
- `k8s-operations.yml`: Comprehensive K8s operations
  - Deployment scaling (manual and HPA)
  - Resource management
  - ConfigMap and Secret updates
  - Pod troubleshooting
  - Service mesh operations

## Usage

### 1. Using Terraform Executor

```python
from app.services.terraform_executor import get_terraform_executor

executor = get_terraform_executor()

# Execute Terraform
result = await executor.execute(
    cloud_provider="aws",
    resource_type="ec2",
    action="apply",
    variables={
        "region": "us-east-1",
        "instance_name": "my-server",
        "instance_type": "t3.micro",
        "os_type": "Linux"
    }
)

# Check outputs
if result["success"]:
    print(f"Instance ID: {result['outputs']['instance_id']}")
```

### 2. Using Ansible Executor

```python
from app.services.ansible_executor import get_ansible_executor

executor = get_ansible_executor()

# Execute Ansible playbook
result = await executor.execute(
    cloud_provider="k8s",
    playbook_name="k8s-operations.yml",
    variables={
        "deployment_name": "my-app",
        "namespace": "production",
        "replicas": 5
    },
    tags=["scale", "deployment"]
)

if result["success"]:
    print("Scaling completed successfully")
```

### 3. Creating New Workflows

To add a new service request (e.g., SageMaker):

#### Step 1: Add Terraform Module
```bash
# Create directory structure
mkdir -p infrastructure/terraform/aws/SAGEMAKER

# Add Terraform files
touch infrastructure/terraform/aws/SAGEMAKER/{main.tf,variables.tf,outputs.tf}
```

#### Step 2: Create Workflow Definition
Create `data/workflows/templates/aws_sagemaker_provisioning.json`:

```json
{
  "workflow_id": "aws_sagemaker_provisioning",
  "name": "AWS SageMaker Endpoint Provisioning",
  "cloud_provider": "aws",
  "resource_type": "sagemaker",
  "input_schema": {
    "type": "object",
    "required": ["region", "endpoint_name", "model_name"],
    "properties": {
      "region": {"type": "string"},
      "endpoint_name": {"type": "string"},
      "model_name": {"type": "string"},
      "instance_type": {"type": "string", "default": "ml.t2.medium"}
    }
  },
  "steps": [
    {
      "step_id": "terraform_plan",
      "type": "terraform",
      "action": "plan",
      "module_path": "aws/SAGEMAKER"
    },
    {
      "step_id": "approval_gate",
      "type": "approval",
      "approval_required": true,
      "dependencies": ["terraform_plan"]
    },
    {
      "step_id": "terraform_apply",
      "type": "terraform",
      "action": "apply",
      "module_path": "aws/SAGEMAKER",
      "dependencies": ["approval_gate"]
    }
  ]
}
```

#### Step 3: No Code Changes Required!

The workflow registry will automatically:
1. Discover the new workflow JSON
2. Generate Pydantic models from the schema
3. Make it available to the provisioner agent
4. Execute with the appropriate Terraform/Ansible executor

## Workflow System Features

### 1. Automatic Discovery
- Workflows are loaded from JSON files at startup
- New workflows detected via file watcher (optional)
- No agent restarts needed (hot reload supported)

### 2. Dynamic Validation
- Pydantic models generated from JSON schemas
- Input validation before execution
- Type-safe workflow execution

### 3. Approval Gates
- Human-in-the-loop approvals configurable per step
- Approval requests sent via UI/API
- Execution pauses until approved

### 4. Multi-Cloud Support
- Single workflow definition works across AWS, Azure, GCP
- Cloud-specific modules selected automatically
- Consistent interface regardless of provider

### 5. Day-2 Operations
- Terraform for infrastructure provisioning (Day-0)
- Ansible for configuration management (Day-2)
- Combined workflows supported

## Best Practices

### Terraform Modules
1. **Use variables.tf** for all configurable inputs
2. **Include outputs.tf** to expose resource IDs, endpoints
3. **Add provider.tf** with version constraints
4. **Document** required variables and outputs

### Ansible Playbooks
1. **Use tags** for selective task execution
2. **Externalize variables** via vars files or extra-vars
3. **Include check mode** support for dry runs
4. **Add handlers** for service restarts, notifications

### Workflow Definitions
1. **Clear naming**: Use descriptive workflow_id and name
2. **Complete schemas**: Define all required and optional fields
3. **Dependencies**: Specify step dependencies explicitly
4. **Approval gates**: Add for destructive or costly operations

## Example: Complete EC2 Workflow

```json
{
  "workflow_id": "aws_ec2_provisioning",
  "name": "AWS EC2 Instance Provisioning",
  "cloud_provider": "aws",
  "resource_type": "ec2",
  "input_schema": {
    "type": "object",
    "required": ["region", "instance_name", "instance_type"],
    "properties": {
      "region": {"type": "string"},
      "instance_name": {"type": "string"},
      "instance_type": {"type": "string"},
      "os_type": {"type": "string", "enum": ["Linux", "Windows"]},
      "volume_size": {"type": "integer", "default": 20}
    }
  },
  "steps": [
    {
      "step_id": "validate",
      "type": "validation",
      "action": "validate_schema"
    },
    {
      "step_id": "terraform_plan",
      "type": "terraform",
      "action": "plan",
      "module_path": "aws/EC2",
      "dependencies": ["validate"]
    },
    {
      "step_id": "approval",
      "type": "approval",
      "approval_required": true,
      "dependencies": ["terraform_plan"]
    },
    {
      "step_id": "terraform_apply",
      "type": "terraform",
      "action": "apply",
      "module_path": "aws/EC2",
      "dependencies": ["approval"]
    },
    {
      "step_id": "ansible_configure",
      "type": "ansible",
      "action": "configure",
      "playbook": "aws-ec2.yml",
      "dependencies": ["terraform_apply"]
    },
    {
      "step_id": "update_snow",
      "type": "snow",
      "action": "update",
      "dependencies": ["ansible_configure"]
    }
  ]
}
```

This workflow:
1. Validates inputs against schema
2. Generates Terraform plan
3. Waits for human approval
4. Applies Terraform configuration
5. Runs Ansible for Day-2 configuration
6. Updates ServiceNow with results

## Monitoring & Observability

All infrastructure operations are:
- **Logged** to structured logs with execution context
- **Traced** via OpenTelemetry spans
- **Metered** with Prometheus metrics
- **Audited** in ServiceNow tickets

Metrics tracked:
- `terraform_execution_duration_seconds`
- `terraform_execution_total{status="success|failed"}`
- `ansible_playbook_duration_seconds`
- `ansible_playbook_total{status="success|failed"}`
- `workflow_step_duration_seconds{step_type}`

## Troubleshooting

### Terraform Errors
```bash
# Check Terraform logs
docker logs aegisops-agent-orchestration | grep terraform

# Validate module syntax
cd infrastructure/terraform/aws/EC2
terraform validate
```

### Ansible Errors
```bash
# Check Ansible logs
docker logs aegisops-agent-orchestration | grep ansible

# Validate playbook syntax
ansible-playbook infrastructure/ansible/aws/aws-ec2.yml --syntax-check
```

### Workflow Not Found
```bash
# List available workflows
curl http://localhost:8002/api/v1/workflows

# Check workflow registry
curl http://localhost:8002/api/v1/workflows/{workflow_id}
```

## Security Considerations

1. **Secrets**: Use environment variables or Vault, never hardcode
2. **State Files**: Terraform state stored in secure backend
3. **Credentials**: AWS/Azure/GCP credentials from environment
4. **Approval Gates**: Required for production deployments
5. **RBAC**: Only operators/admins can execute infrastructure workflows

## References

- [Terraform Best Practices](https://www.terraform.io/docs/cloud/guides/recommended-practices/index.html)
- [Ansible Best Practices](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html)
- [AegisOps HLD](../../Ops%20HLD%20Final.txt)
- [Workflow Schema](../../data/workflows/schemas/)
