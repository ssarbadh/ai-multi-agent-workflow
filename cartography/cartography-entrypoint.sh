#!/bin/bash
# Entrypoint for Cartography with EKS support.
# - Filters kubeconfig to a single context if CARTOGRAPHY_K8S_CONTEXT is set
# - Ensures AWS credentials (profile or keys) are available for aws eks get-token

set -e

KUBECONFIG_SOURCE="${KUBECONFIG_SOURCE:-/var/cartography/.kube/config}"
KUBECONFIG_FILTERED="/tmp/kubeconfig-cartography.yaml"
CONTEXT="${CARTOGRAPHY_K8S_CONTEXT:-}"

# If CARTOGRAPHY_K8S_CONTEXT is set, filter kubeconfig to that context only
if [ -n "$CONTEXT" ] && [ -f "$KUBECONFIG_SOURCE" ]; then
    AWS_PROFILE_OVERRIDE="${CARTOGRAPHY_AWS_PROFILE:-}"
    python3 - "$KUBECONFIG_SOURCE" "$CONTEXT" "$KUBECONFIG_FILTERED" "$AWS_PROFILE_OVERRIDE" << 'PYTHON'
import sys
import yaml

def filter_kubeconfig(src_path, context_name, dst_path, aws_profile_override):
    with open(src_path) as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        sys.exit(1)
    clusters = cfg.get("clusters", [])
    contexts = cfg.get("contexts", [])
    users = cfg.get("users", [])

    ctx_entry = next((c for c in contexts if c.get("name") == context_name), None)
    if not ctx_entry:
        print(f"Context '{context_name}' not found in kubeconfig", file=sys.stderr)
        sys.exit(1)

    cluster_name = ctx_entry.get("context", {}).get("cluster")
    user_name = ctx_entry.get("context", {}).get("user")
    if not cluster_name or not user_name:
        print("Context missing cluster or user", file=sys.stderr)
        sys.exit(1)

    filtered_clusters = [c for c in clusters if c.get("name") == cluster_name]
    filtered_contexts = [c for c in contexts if c.get("name") == context_name]
    filtered_users = [u for u in users if u.get("name") == user_name]

    # Override AWS_PROFILE in exec user's env if CARTOGRAPHY_AWS_PROFILE is set
    if aws_profile_override and filtered_users:
        for u in filtered_users:
            exec_cfg = u.get("exec")
            if exec_cfg:
                env_list = exec_cfg.get("env") or []
                env_dict = {e["name"]: e["value"] for e in env_list if "name" in e and "value" in e}
                env_dict["AWS_PROFILE"] = aws_profile_override
                exec_cfg["env"] = [{"name": k, "value": v} for k, v in env_dict.items()]

    out = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": filtered_clusters,
        "contexts": filtered_contexts,
        "current-context": context_name,
        "users": filtered_users,
    }
    with open(dst_path, "w") as f:
        yaml.dump(out, f, default_flow_style=False, allow_unicode=True)
    print(f"Filtered kubeconfig to context '{context_name}' -> {dst_path}")

if __name__ == "__main__":
    filter_kubeconfig(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
PYTHON
    KUBECONFIG_FINAL="$KUBECONFIG_FILTERED"
else
    KUBECONFIG_FINAL="$KUBECONFIG_SOURCE"
fi

# Build cartography args, replacing --k8s-kubeconfig if we filtered
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --k8s-kubeconfig=*)
            if [ -n "$CONTEXT" ]; then
                ARGS+=("--k8s-kubeconfig=$KUBECONFIG_FINAL")
            else
                ARGS+=("$arg")
            fi
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

# If no args from CMD, use defaults (kubernetes + aws with selective resources)
if [ ${#ARGS[@]} -eq 0 ]; then
    AWS_PROFILE_VAL="${CARTOGRAPHY_AWS_PROFILE:-ct-nonprod}"
    if [ -n "$AWS_PROFILE_VAL" ]; then
        export AWS_PROFILE="$AWS_PROFILE_VAL"
    fi
    # Valid names: see cartography error message / docs (e.g. ec2:network_acls not ec2:network_acl)
    # Include ec2:network_interface (ALB/NLB expose) and ec2:vpc_endpoint (route table associations)
    AWS_SYNCS="${CARTOGRAPHY_AWS_REQUESTED_SYNCS:-ec2:instance,ec2:subnet,ec2:security_group,ec2:route_table,ec2:network_acls,ec2:network_interface,ec2:vpc_endpoint,ec2:load_balancer,ec2:load_balancer_v2,rds,elasticache}"
    AWS_REGIONS="${CARTOGRAPHY_AWS_REGIONS:-eu-west-1}"
    set -- --neo4j-uri="${NEO4J_URI:-bolt://neo4j:7687}" \
        --neo4j-user="${NEO4J_USER:-neo4j}" \
        --neo4j-password-env-var=NEO4J_PASSWORD \
        --selected-modules=kubernetes,aws \
        --aws-requested-syncs="$AWS_SYNCS" \
        --aws-regions="$AWS_REGIONS" \
        --k8s-kubeconfig="$KUBECONFIG_FINAL" \
        --managed-kubernetes=eks
else
    set -- "${ARGS[@]}"
fi

exec cartography "$@"
